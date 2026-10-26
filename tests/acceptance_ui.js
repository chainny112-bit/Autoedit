// Acceptance tests 1-7 (Module 14 / Feature 7), driven through the real web UI with Playwright.
// Usage: (server NOT running)  node tests/acceptance_ui.js      — starts/stops/restarts the server itself.
const { chromium } = require('playwright');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const BASE = 'http://localhost:8000';
const SHOTS = path.join(ROOT, 'docs/screenshots');
const results = [];
let server;

function startServer() {
  server = spawn('python3', ['app.py'], { cwd: ROOT, stdio: ['ignore', fs.openSync('/tmp/autoedit_test_server.log', 'a'), fs.openSync('/tmp/autoedit_test_server.log', 'a')] });
}
async function waitUp() { for (let i = 0; i < 60; i++) { try { const r = await fetch(BASE + '/api/env'); if (r.ok) return; } catch {} await new Promise(r => setTimeout(r, 500)); } throw new Error('server did not start'); }
function stopServer() { return new Promise(res => { server.on('exit', res); server.kill('SIGTERM'); }); }
const now = () => Date.now() / 1000;
const api = async (p, o) => { const r = await fetch(BASE + p, o); if (!r.ok) throw new Error(p + ' ' + r.status + ' ' + await r.text()); return r.json(); };
function record(n, name, pass, detail) { results.push({ test: n, name, pass, detail }); console.log(`TEST ${n} ${pass ? 'PASS' : 'FAIL'} — ${name}: ${detail}`); }
// Waits until a variant reaches one of `states` with a result produced *after* `since` (seconds since epoch),
// so an earlier identical status never counts as the new result.
async function waitVariant(jid, vid, states, timeout = 600000, since = 0) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    const j = await api(`/api/jobs/${jid}`); const v = j.variants[vid];
    const fresh = !since || (v && ((v.status === 'plan_ready' && (v.planned_at || 0) > since) ||
      (v.status === 'preview_ready' && ((v.outputs.preview || {}).t || 0) > since) ||
      (v.status === 'done' && ((v.outputs.final || {}).t || 0) > since)));
    if (v && states.includes(v.status) && fresh) return j;
    if (v && v.status === 'error') throw new Error(`${vid}: ${v.message}`);
    if (j.status === 'error') throw new Error(j.message);
    await new Promise(r => setTimeout(r, 2000));
  }
  throw new Error(`timeout waiting for ${vid} ${states}`);
}
function ffprobeOk(file) {
  const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,width,height', '-show_entries', 'format=duration', '-of', 'json', file]).toString();
  const j = JSON.parse(out); execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'null', '-']);   // full decode, throws on corruption
  return j;
}

(async () => {
  startServer(); await waitUp();
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1400, height: 1000 } });
  const errors = []; p.on('pageerror', e => errors.push(e.message));
  let jid;
  try {
    // ---------------- TEST 1: upload + RedRabbit Signature -> real render
    await p.goto(BASE + '/'); await p.waitForSelector('.env-item');
    await p.selectOption('#presetSel', 'redrabbit_signature');
    await p.setInputFiles('#fVideo', path.join(ROOT, 'samples/business_sample_talking_head.mp4'));
    await p.setInputFiles('#fTranscript', path.join(ROOT, 'samples/business_sample.srt'));
    await p.screenshot({ path: path.join(SHOTS, '1_upload_style.png'), fullPage: true });
    await p.click('#btnStart');
    await p.waitForSelector('#view-job:not(.hidden)');
    jid = (await p.evaluate(() => JOB.id));
    let j = await waitVariant(jid, 'main', ['done'], 900000);
    const fin = path.join(ROOT, 'data/jobs', jid, j.variants.main.outputs.final.file);
    const pr = ffprobeOk(fin);
    const plan1 = await api(`/api/jobs/${jid}/variants/main/plan`);
    const errs1 = j.variants.main.outputs.final.qc.filter(i => i.level === 'error');
    record(1, 'อัปโหลด + REDRABBIT SIGNATURE แล้วเรนเดอร์ได้จริง', pr.streams[0].width === 1080 && pr.streams[0].height === 1920 && plan1.settings.preset_id === 'redrabbit_signature' && plan1.settings.accent.toUpperCase() === '#BC0000' && errs1.length === 0,
      `preset=${plan1.settings.preset_id} accent=${plan1.settings.accent} ${pr.streams[0].width}x${pr.streams[0].height} ${(+pr.format.duration).toFixed(1)}s QC errors=${errs1.length}`);
    await p.waitForTimeout(2500); await p.screenshot({ path: path.join(SHOTS, '2_job_effect_map.png'), fullPage: true });

    // ---------------- TEST 2: density MINIMAL -> DYNAMIC changes the plan (via the style bar, no re-analysis)
    const countFx = (pl) => pl.segments.filter(s => s.keep).reduce((n, s) => n + (s.effects || []).length, 0);
    const graphics = (pl) => pl.segments.filter(s => s.keep && (s.effects.length || ['pip', 'split', 'broll_full'].includes(s.layout))).length;
    const anaBefore = fs.statSync(path.join(ROOT, 'data/jobs', jid, 'analysis.json')).mtimeMs;
    let t2 = now(); await p.selectOption('#vDensity', '1'); await p.click('#btnRestyle');
    await waitVariant(jid, 'main', ['plan_ready'], 300000, t2); const pMin = await api(`/api/jobs/${jid}/variants/main/plan`);
    await p.waitForTimeout(2000);
    t2 = now(); await p.selectOption('#vDensity', '3'); await p.click('#btnRestyle');
    await waitVariant(jid, 'main', ['plan_ready'], 300000, t2); const pDyn = await api(`/api/jobs/${jid}/variants/main/plan`);
    const anaAfter = fs.statSync(path.join(ROOT, 'data/jobs', jid, 'analysis.json')).mtimeMs;
    record(2, 'ปรับ Density MINIMAL → DYNAMIC แล้ว Editing Plan เปลี่ยนตาม', pMin.direction.density === 1 && pDyn.direction.density === 3 && countFx(pDyn) > countFx(pMin) && graphics(pDyn) >= graphics(pMin) && anaBefore === anaAfter,
      `MINIMAL: เอฟเฟกต์ ${countFx(pMin)} จุด/ช่วงกราฟิก ${graphics(pMin)} → DYNAMIC: ${countFx(pDyn)} จุด/${graphics(pDyn)} · ไม่วิเคราะห์ใหม่ (analysis.json ไม่เปลี่ยน)=${anaBefore === anaAfter}`);

    // ---------------- TEST 3: custom preset survives a restart
    await p.click('.tab[data-view=presets]'); await p.click('#btnNewPreset');
    await p.fill('#peBody [name=name]', 'ทดสอบ ลูกค้า A'); await p.uncheck('#peBody [name=use_brand]');
    await p.fill('#peBody [name=accent]', '#1E88E5'); await p.selectOption('#peBody [name=density]', '3');
    await p.selectOption('#peBody [name=subtitle_font]', 'Prompt Bold');
    await p.selectOption('#peBody [data-fx=vertigo]', 'ban');
    await p.click('#peSave'); await p.waitForTimeout(800);
    await p.screenshot({ path: path.join(SHOTS, '3_preset_manager.png'), fullPage: true });
    const onDisk = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/presets.json'), 'utf8'));
    const saved = Object.values(onDisk.presets).find(x => x.name === 'ทดสอบ ลูกค้า A');
    await stopServer(); startServer(); await waitUp();          // close + reopen the program
    await p.goto(BASE + '/'); await p.waitForSelector('.env-item');
    const opts = await p.$$eval('#presetSel option', os => os.map(o => o.textContent));
    await p.selectOption('#presetSel', saved.id);
    const accent = await p.$eval('[name=accent]', e => e.value), font = await p.$eval('[name=subtitle_font]', e => e.value);
    record(3, 'บันทึก Custom Preset แล้วเรียกใช้ได้หลังปิด/เปิดโปรแกรมใหม่', !!saved && opts.some(o => o.includes('ทดสอบ ลูกค้า A')) && accent.toLowerCase() === '#1e88e5' && font === 'Prompt Bold' && saved.banned_effects.includes('vertigo'),
      `id=${saved && saved.id} หลังรีสตาร์ท: อยู่ในรายการ=${opts.some(o => o.includes('ทดสอบ ลูกค้า A'))} accent=${accent} font=${font} banned=${saved && saved.banned_effects}`);

    // ---------------- TEST 4: CLEAN / CINEMATIC / HIGH RETENTION from the same source
    await p.goto(BASE + '/#job=' + jid); await p.waitForSelector('#btnVariations:not([disabled])', { timeout: 60000 });
    await p.click('#btnVariations');
    for (const k of ['clean', 'cinematic', 'retention']) await p.check(`#varChoices input[value=${k}]`);
    for (const k of ['creative', 'auto']) await p.uncheck(`#varChoices input[value=${k}]`);
    await p.check('#varPreview'); await p.click('#varGo');
    for (const v of ['clean', 'cinematic', 'retention']) await waitVariant(jid, v, ['preview_ready'], 900000);
    const cmp = await api(`/api/jobs/${jid}/compare`);
    const vs = Object.fromEntries(cmp.variants.map(v => [v.id, v]));
    const plans = {}; for (const v of ['clean', 'cinematic', 'retention']) plans[v] = await api(`/api/jobs/${jid}/variants/${v}/plan`);
    const files = ['clean', 'cinematic', 'retention'].map(v => path.join(ROOT, 'data/jobs', jid, vs[v].outputs.preview.file));
    const distinct = new Set(files).size === 3 && files.every(f => fs.existsSync(f));
    const sameSource = new Set(Object.values(plans).map(pl => pl.source.path || pl.source.duration)).size === 1;
    const sameText = Object.values(plans).every(pl => JSON.stringify(pl.segments.map(s => s.text)) === JSON.stringify(plans.clean.segments.map(s => s.text)));
    const presetsUsed = ['clean', 'cinematic', 'retention'].map(v => plans[v].settings.preset_id);
    await p.waitForTimeout(3000); await p.selectOption('#cmpSeg', { index: 1 });
    await p.screenshot({ path: path.join(SHOTS, '4_comparison_dashboard.png'), fullPage: false });
    record(4, 'สร้าง CLEAN / CINEMATIC / HIGH RETENTION จากต้นฉบับเดียว มี Timeline และผลลัพธ์แยกกัน', distinct && sameSource && sameText && new Set(presetsUsed).size === 3,
      `presets=${presetsUsed.join(',')} ไฟล์แยก=${distinct} บทพูดเดียวกัน=${sameText} เอฟเฟกต์: ` + ['clean', 'cinematic', 'retention'].map(v => `${v}[${(vs[v].stats.main_effects || []).join('/') || '-'}]`).join(' '));

    // ---------------- TEST 5: export only the chosen version
    const t5 = now(); await p.click('[data-exp=retention]');
    let j5 = await waitVariant(jid, 'retention', ['done'], 900000, t5);
    const finals = Object.fromEntries(Object.entries(j5.variants).map(([k, v]) => [k, !!v.outputs.final]));
    const rf = path.join(ROOT, 'data/jobs', jid, j5.variants.retention.outputs.final.file);
    record(5, 'เลือก Export เฉพาะเวอร์ชันที่ต้องการ', finals.retention && !finals.clean && !finals.cinematic && fs.existsSync(rf),
      `final: ${JSON.stringify(finals)} (main ถูก export ใน TEST 1)`);

    // ---------------- TEST 6: AI API unavailable -> status + fallback
    const env = await api('/api/env');
    const paper = env.effects.find(e => e.id === 'paper_cut');
    const pf = await api(`/api/jobs/${jid}/variants/main/preflight?kind=final`);
    const aiApi = pf.apis.find(a => a.name.startsWith('AI Image'));
    await p.click('.tab[data-view=effects]'); await p.waitForTimeout(500);
    const effText = await p.textContent('#effectGrid');
    await p.screenshot({ path: path.join(SHOTS, '5_effect_library.png'), fullPage: true });
    // render one segment with Paper Cut (needs AI image for best result) and confirm the fallback is used and reported
    const pl = await api(`/api/jobs/${jid}/variants/clean/plan`);
    const seg = pl.segments.find(s => s.keep && s.role !== 'hook');
    seg.effects = [{ id: 'paper_cut', params: {}, reason: 'TEST 6', auto: false }]; seg.layout = 'pip';
    await api(`/api/jobs/${jid}/variants/clean/plan`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pl) });
    const t6 = now();
    await api(`/api/jobs/${jid}/variants/clean/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    await waitVariant(jid, 'clean', ['preview_ready'], 600000, t6);
    const rep6 = await api(`/api/jobs/${jid}/files/variants/clean/qc_preview.json`);
    const paperRendered = rep6.effects_report.some(r => r.effect === 'paper_cut' && r.status === 'rendered');
    const pf6 = await api(`/api/jobs/${jid}/variants/clean/preflight?kind=final`);
    record(6, 'AI API ไม่พร้อม → แจ้งสถานะและใช้ Fallback', !env.capabilities.ai_image.ok && aiApi && !aiApi.available && paper.degraded && effText.includes('ai_image') && paperRendered && pf6.effect_fallbacks.some(x => x.includes('Paper Cut')),
      `capability ai_image=${env.capabilities.ai_image.ok} · preflight: "${aiApi && aiApi.when}" · Paper Cut: ${paper.degraded_reason} → เรนเดอร์ด้วย fallback=${paperRendered} · แจ้งใน preflight: ${pf6.effect_fallbacks.join(' | ')}`);

    // ---------------- TEST 7: files play, A/V + subtitles in sync, not corrupt
    const j7 = await api(`/api/jobs/${jid}`);
    const outs = [];
    for (const [k, v] of Object.entries(j7.variants)) for (const kind of ['preview', 'final']) if (v.outputs[kind]) outs.push([k, kind, v.outputs[kind]]);
    const bad = [];
    for (const [k, kind, o] of outs) {
      const f = path.join(ROOT, 'data/jobs', jid, o.file);
      const pj = ffprobeOk(f);
      const vdur = +pj.format.duration;
      if (pj.streams.length < 2 || Math.abs(vdur - o.duration) > 0.3) bad.push(`${k}/${kind} duration ${vdur} vs ${o.duration}`);
      const syncErr = o.qc.filter(i => ['sub_sync', 'decode', 'unplayable', 'black', 'word_cut', 'true_peak', 'compat'].includes(i.code));
      if (syncErr.length) bad.push(`${k}/${kind}: ${syncErr.map(i => i.message).join(';')}`);
    }
    await p.goto(BASE + '/#job=' + jid); await p.waitForTimeout(3000);
    const playable = await p.evaluate(async () => { const v = document.querySelector('#vFinal'); if (!v.src) return 'no src'; await v.play().catch(e => e.message); await new Promise(r => setTimeout(r, 1500)); const t = v.currentTime; v.pause(); return t > 0.5 ? 'ok' : 'stuck ' + t; });
    record(7, 'ไฟล์เปิดเล่นได้จริง เสียง/ซับซิงก์ ไม่มีไฟล์เสีย', bad.length === 0 && playable === 'ok',
      `ตรวจ ${outs.length} ไฟล์ (ffprobe + ถอดรหัสทั้งไฟล์ + QC sync) ปัญหา=${bad.length ? bad.join(' | ') : 'ไม่มี'} · เล่นในเบราว์เซอร์=${playable}`);
  } catch (e) {
    record('X', 'error', false, e.stack || String(e));
  } finally {
    record('JS', 'ไม่มี JavaScript error ในหน้าเว็บ', errors.length === 0, errors.join(' | ') || 'ไม่มี');
    fs.writeFileSync(path.join(ROOT, 'docs/acceptance_results.json'), JSON.stringify({ job: jid, when: new Date().toISOString(), results }, null, 1));
    await b.close(); await stopServer();
  }
})();
