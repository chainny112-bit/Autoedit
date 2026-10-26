"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (t) => { t = Math.max(0, t || 0); const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`; };
const ACTIVE = ["queued", "analyzing", "planning", "previewing", "rendering"];
const STATUS_TH = { new: "ใหม่", queued: "รอคิว", analyzing: "กำลังวิเคราะห์", planning: "กำลังวางแผน", plan_ready: "แผนพร้อม",
  previewing: "สร้าง Preview", preview_ready: "Preview พร้อม", rendering: "กำลังเรนเดอร์", done: "เสร็จสิ้น", error: "ผิดพลาด",
  cancelled: "ยกเลิกแล้ว", uploaded: "อัปโหลดแล้ว", ready: "วิเคราะห์เสร็จ" };
const LAYOUT_TH = { full: "ผู้พูดเต็มจอ", pip: "ภาพประกอบบน / ผู้พูดล่าง", split: "Split เปรียบเทียบ", broll_full: "ภาพประกอบเต็มจอ", fit: "Fit + พื้นหลังเบลอ" };
const ZOOM_TH = { none: "Medium (ไม่ซูม)", punch: "Punch-in", close: "Close-up" };
const BROLL_TH = { none: "— ไม่มี —", stat: "การ์ดตัวเลข", steps: "ลำดับขั้นตอน", timeline: "Timeline ปี", keyword: "การ์ดคำสำคัญ", compare: "เปรียบเทียบ 2 ฝั่ง", placeholder: "Placeholder (ต้องสร้างภาพ)", asset: "ไฟล์ภาพ/วิดีโอ" };
const SFX_TH = { none: "ไม่มี", whoosh: "Whoosh", pop: "Pop", hit: "Hit" };
const TRANS_TH = { cut: "Cut (ตัดตรง)", flash: "Flash สีแบรนด์", zoom_through: "Zoom-through" };
const ROLE_TH = { hook: "Hook", point: "ประเด็น", example: "ตัวอย่าง", steps: "ขั้นตอน", turn: "จุดเปลี่ยน", conclusion: "สรุป/CTA" };
const IMPL_TH = { real: ["ทำงานจริง", "ok"], simulation: ["จำลอง", "sim"], needs_api: ["ต้องใช้ API", "api"] };

let ENV = null, PRESETS = [], PROJECTS = [], PROJECT = "default", JOB = null, VID = "main", PLAN = null, PLAN_VID = null;
let CMP = null, pollTimer = null, planDirty = false, lastStatusKey = "", MODE = "auto", DENSITY = 2, INTENSITY = "medium";
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 5000);
}
async function api(path, opts = {}) {
  if (opts.json !== undefined) { opts.body = JSON.stringify(opts.json); opts.headers = { "Content-Type": "application/json" }; delete opts.json; }
  const r = await fetch(path, opts);
  if (!r.ok) { let m = r.statusText; try { const j = await r.json(); m = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {} throw new Error(m); }
  return r.json();
}
function show(view) {
  $$(".view").forEach((v) => v.classList.add("hidden")); $("#view-" + view).classList.remove("hidden");
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  if (view === "history") loadHistory();
  if (view === "presets") renderPresetList();
  if (view === "effects") renderEffects();
}
$$(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
const opt = (map, val) => Object.entries(map).map(([k, v]) => `<option value="${esc(k)}" ${String(k) === String(val) ? "selected" : ""}>${esc(v)}</option>`).join("");
const fxName = (id) => (ENV.effects.find((e) => e.id === id) || { name: id }).name;

// ---------------------------------------------------------------- environment, presets, projects
async function loadEnv() {
  ENV = await api("/api/env");
  const names = { ffmpeg: "FFmpeg (libass/x264/aac)", ffprobe: "FFprobe", fonts: "ฟอนต์ไทย", speech_to_text: "Speech-to-Text", face_detection: "ตรวจจับใบหน้า",
    thai_nlp: "ตัดคำภาษาไทย", llm_story_analysis: "วิเคราะห์เรื่องด้วย AI (มีค่าใช้จ่าย)", ai_image: "สร้างภาพ AI" };
  const caps = ENV.capabilities;
  const items = Object.entries(names).map(([k, n]) => [n, caps[k].ok, caps[k].detail, caps[k].required]);
  items.push(["แยกตัวบุคคล (Segmentation)", ENV.effect_caps.segmentation, ENV.effect_caps.segmentation_detail, false]);
  $("#envList").innerHTML = items.map(([n, ok, d, req]) => `<div class="env-item ${ok ? "ok" : "bad"} ${req ? "req" : ""}"><b>${n}</b><span class="muted">${esc(d)}</span></div>`).join("");
  const warn = [];
  if (!caps.ready) warn.push("⛔ เครื่องมือที่จำเป็นไม่ครบ (FFmpeg/ฟอนต์) — ระบบยังเรนเดอร์ไม่ได้");
  if (!caps.speech_to_text.ok) warn.push("⚠️ ไม่มี Speech-to-Text — ต้องแนบไฟล์ .srt/.vtt มากับวิดีโอ");
  $("#envBanner").innerHTML = warn.join("<br>"); $("#envBanner").classList.toggle("hidden", !warn.length);
  $("#chkLlm").disabled = !caps.llm_story_analysis.ok; $("#chkAi").disabled = !caps.ai_image.ok;
  if (!caps.llm_story_analysis.ok) $("#chkLlm").closest("label").title = "ไม่มี ANTHROPIC_API_KEY";
  if (!caps.ai_image.ok) $("#chkAi").closest("label").title = "ไม่ได้ตั้งค่า AUTOEDIT_IMAGE_CMD";
  $("#fontSel").innerHTML = ENV.fonts.map((f) => `<option>${esc(f)}</option>`).join("");
  $("#profileSel").innerHTML = opt(ENV.profiles, "1080p_high");
  $("#vProfile").innerHTML = opt(ENV.profiles, "1080p_high");
  $("#modeSeg").innerHTML = Object.entries(ENV.modes).map(([k, m]) => `<button type="button" data-v="${k}">${esc(m.name.split(" — ")[0])} ${esc(m.name.split(" — ")[1] || "")}</button>`).join("");
  $("#densitySeg").innerHTML = Object.entries(ENV.densities).map(([k, d]) => `<button type="button" data-v="${k}">${k} ${esc(d.name)}</button>`).join("");
  $("#intensitySeg").innerHTML = ["low", "medium", "high"].map((k) => `<button type="button" data-v="${k}">${k.toUpperCase()}</button>`).join("");
  $("#vMode").innerHTML = opt(Object.fromEntries(Object.entries(ENV.modes).map(([k, m]) => [k, m.name])), "auto");
  $("#vDensity").innerHTML = opt(Object.fromEntries(Object.entries(ENV.densities).map(([k, d]) => [k, `${k} ${d.name}`])), 2);
  bindSeg("#modeSeg", (v) => { MODE = v; $("#modeDesc").textContent = ENV.modes[v].desc; });
  bindSeg("#densitySeg", (v) => { DENSITY = +v; $("#densityDesc").textContent = ENV.densities[v].desc; });
  bindSeg("#intensitySeg", (v) => { INTENSITY = v; });
}
function bindSeg(sel, cb) {
  $$(`${sel} button`).forEach((b) => b.addEventListener("click", () => { setSeg(sel, b.dataset.v); cb(b.dataset.v); }));
}
function setSeg(sel, v) { $$(`${sel} button`).forEach((b) => b.classList.toggle("active", b.dataset.v === String(v))); }

async function loadPresets() {
  PRESETS = await api("/api/presets");
  const cur = $("#presetSel").value;
  const html = PRESETS.map((p) => `<option value="${p.id}">${esc(p.name)}${p.builtin ? "" : " · (ของฉัน)"}</option>`).join("");
  $("#presetSel").innerHTML = html; $("#vPreset").innerHTML = `<option value="">— ตามค่าที่ตั้งตอนสร้างงาน —</option>` + html;
  if (cur && PRESETS.some((p) => p.id === cur)) $("#presetSel").value = cur;
}
async function loadProjects() {
  PROJECTS = await api("/api/projects");
  const saved = store.get("autoedit.project");
  if (saved && PROJECTS.some((p) => p.id === saved)) PROJECT = saved;
  $("#projectSel").innerHTML = PROJECTS.map((p) => `<option value="${p.id}" ${p.id === PROJECT ? "selected" : ""}>${esc(p.name)}</option>`).join("");
}
function applyPreset(p, keepColorsFromBrand = true) {
  if (!p) return;
  const proj = PROJECTS.find((x) => x.id === PROJECT);
  const brand = (proj && proj.memory && proj.memory.brand) || {};
  $("#presetDesc").textContent = p.description || "";
  const f = (n) => $(`#settingsForm [name=${n}]`);
  f("accent").value = p.accent || brand.accent || "#BC0000";
  f("accent2").value = p.accent2 || brand.accent2 || "#A8CE20";
  f("subtitle_mode").value = p.subtitle_mode; f("subtitle_font").value = p.subtitle_font;
  f("subtitle_size").value = p.subtitle_size; $("#subSizeOut").textContent = p.subtitle_size;
  f("pacing").value = p.pacing; f("export_profile").value = p.export_profile; f("music").value = p.music;
  f("music_db").value = p.music_db; $("#musicOut").textContent = p.music_db;
  f("sfx").checked = p.sfx; f("title_cards").checked = p.title_cards;
  MODE = p.mode; DENSITY = p.density; INTENSITY = p.intensity;
  setSeg("#modeSeg", MODE); setSeg("#densitySeg", DENSITY); setSeg("#intensitySeg", INTENSITY);
  $("#modeDesc").textContent = ENV.modes[MODE].desc; $("#densityDesc").textContent = ENV.densities[DENSITY].desc;
}
function applyMemory() {
  const proj = PROJECTS.find((x) => x.id === PROJECT);
  const mem = (proj && proj.memory) || {};
  const pid = mem.preset_id && PRESETS.some((p) => p.id === mem.preset_id) ? mem.preset_id : PRESETS[0].id;
  $("#presetSel").value = pid;
  applyPreset(PRESETS.find((p) => p.id === pid));
  const ov = mem.overrides || {};
  for (const [k, v] of Object.entries(ov)) {
    const el = $(`#settingsForm [name=${k}]`);
    if (k === "mode") { MODE = v; setSeg("#modeSeg", v); $("#modeDesc").textContent = ENV.modes[v].desc; continue; }
    if (k === "density") { DENSITY = +v; setSeg("#densitySeg", v); $("#densityDesc").textContent = ENV.densities[v].desc; continue; }
    if (k === "intensity") { INTENSITY = v; setSeg("#intensitySeg", v); continue; }
    if (!el) continue;
    if (el.type === "checkbox") el.checked = v === true || v === "on"; else el.value = v;
  }
  if (mem.brand && mem.brand.brand_name) $("#settingsForm [name=brand_name]").value = mem.brand.brand_name;
  $("#memoryNote").textContent = mem.updated ? `จำค่าล่าสุดของโปรเจกต์ "${proj.name}"` : "";
  $("#subSizeOut").textContent = $("#settingsForm [name=subtitle_size]").value;
}
$("#presetSel").addEventListener("change", () => applyPreset(PRESETS.find((p) => p.id === $("#presetSel").value)));
$("#projectSel").addEventListener("change", () => { PROJECT = $("#projectSel").value; store.set("autoedit.project", PROJECT); applyMemory(); });
$("#btnNewProject").addEventListener("click", async () => {
  const name = prompt("ชื่อโปรเจกต์/ลูกค้าใหม่"); if (!name) return;
  try { const p = await api("/api/projects", { method: "POST", json: { name } }); PROJECT = p.id; store.set("autoedit.project", PROJECT); await loadProjects(); applyMemory(); toast(`สร้างโปรเจกต์ "${p.name}" แล้ว`); }
  catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- new job form
const fVideo = $("#fVideo");
function videoChosen() {
  const f = fVideo.files[0]; $("#nVideo").textContent = f ? `${f.name} · ${(f.size / 1048576).toFixed(1)} MB` : "";
  $("#btnStart").disabled = !f; $("#startHint").textContent = f ? "ระบบจะวิเคราะห์ → AI Director เลือกเอฟเฟกต์ → เรนเดอร์ → ตรวจ QC ให้อัตโนมัติ" : "เลือกไฟล์วิดีโอก่อน";
}
fVideo.addEventListener("change", videoChosen);
const drop = $("#dropVideo");
["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (ev) => { if (ev.dataTransfer.files.length) { fVideo.files = ev.dataTransfer.files; videoChosen(); } });
$("#fRefs").addEventListener("change", (e) => { $("#refThumbs").innerHTML = [...e.target.files].map((f) => `<img src="${URL.createObjectURL(f)}" alt="">`).join(""); });
const bindOut = (name, out) => { const i = $(`[name=${name}]`); i.addEventListener("input", () => ($(out).textContent = i.value)); };
bindOut("subtitle_size", "#subSizeOut"); bindOut("music_db", "#musicOut");
$("#fMusic").addEventListener("change", () => { if ($("#fMusic").files.length) $("[name=music]").value = "upload"; });

function readSettings() {
  const s = {};
  $$("#settingsForm [name]").forEach((el) => {
    if (el.type === "checkbox") s[el.name] = el.checked;
    else if (el.type === "range") s[el.name] = parseFloat(el.value);
    else s[el.name] = el.value;
  });
  s.fps = s.fps === "source" ? "source" : parseFloat(s.fps);
  s.use_llm = s.use_llm ? "on" : "off";
  if (!s.use_reference_colors) s.accent_locked = true;
  s.mode = MODE; s.density = DENSITY; s.intensity = INTENSITY;
  return s;
}
$("#btnSaveAsPreset").addEventListener("click", async () => {
  const name = prompt("ชื่อ Preset ใหม่"); if (!name) return;
  const s = readSettings();
  const base = PRESETS.find((p) => p.id === $("#presetSel").value) || {};
  const data = { ...base, ...s, name, description: `สร้างจาก ${base.name || "ค่าปัจจุบัน"}` };
  try { const p = await api("/api/presets", { method: "POST", json: data }); await loadPresets(); $("#presetSel").value = p.id; applyPreset(p); toast(`บันทึก Preset "${p.name}" ลงไฟล์แล้ว`); }
  catch (e) { toast("บันทึกไม่สำเร็จ: " + e.message, true); }
});

$("#btnStart").addEventListener("click", () => {
  const fd = new FormData();
  fd.append("video", fVideo.files[0]);
  fd.append("settings", JSON.stringify(readSettings()));
  fd.append("project_id", PROJECT);
  fd.append("preset_id", $("#presetSel").value);
  if ($("#fTranscript").files[0]) fd.append("transcript", $("#fTranscript").files[0]);
  if ($("#fMusic").files[0]) fd.append("music", $("#fMusic").files[0]);
  [...$("#fRefs").files].forEach((f) => fd.append("references", f));
  [...$("#fBroll").files].forEach((f) => fd.append("broll", f));
  fd.append("broll_source", $("#brollSource").value);
  fd.append("start", "auto");
  $("#btnStart").disabled = true;
  const up = $("#upProg"); up.classList.remove("hidden");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) { $("i", up).style.width = (100 * e.loaded / e.total) + "%"; $("span", up).textContent = `อัปโหลด ${Math.round(100 * e.loaded / e.total)}%`; } };
  xhr.onload = async () => {
    $("#btnStart").disabled = false; up.classList.add("hidden");
    let data; try { data = JSON.parse(xhr.responseText); } catch { data = {}; }
    if (xhr.status >= 300) { toast(data.detail || "อัปโหลดไม่สำเร็จ", true); return; }
    await loadProjects();
    openJob(data.id);
  };
  xhr.onerror = () => { $("#btnStart").disabled = false; toast("อัปโหลดไม่สำเร็จ (เครือข่าย)", true); };
  xhr.send(fd);
});

// ---------------------------------------------------------------- job view
async function openJob(id) {
  PLAN = null; PLAN_VID = null; planDirty = false; VID = "main"; lastStatusKey = "";
  $("#tabJob").disabled = false; show("job");
  history.replaceState(null, "", "#job=" + id);
  await refreshJob(id);
}
async function refreshJob(id) {
  let job;
  try { job = await api(`/api/jobs/${id || JOB.id}`); } catch (e) { toast(e.message, true); return; }
  JOB = job;
  if (!job.variants[VID]) VID = "main";
  $("#jobTitle").textContent = job.title;
  $("#jobId").textContent = `งาน ${job.id} · ${new Date(job.created * 1000).toLocaleString("th-TH")} · โปรเจกต์ ${(PROJECTS.find((p) => p.id === job.project) || {}).name || "-"}`;
  $("#anaBar").style.width = Math.round((job.status === "ready" ? 1 : job.progress || 0) * 100) + "%";
  $("#anaMsg").textContent = `การวิเคราะห์: ${STATUS_TH[job.status] || job.status}` + (job.message && job.status !== "ready" ? ` — ${job.message}` : "");
  const lb = $("#logBox"); const atBottom = lb.scrollTop + lb.clientHeight >= lb.scrollHeight - 20;
  lb.textContent = (job.log || []).join("\n"); if (atBottom) lb.scrollTop = lb.scrollHeight;
  const anyBusy = ACTIVE.includes(job.status) || Object.values(job.variants).some((v) => ACTIVE.includes(v.status));
  $("#btnReanalyze").disabled = anyBusy; $("#btnVariations").disabled = anyBusy || job.status !== "ready";
  renderVariantTabs(); renderVariantPanel(); renderAssets(job);
  // reload plan when the active variant gets a new plan
  const v = job.variants[VID];
  const key = `${VID}:${v.status}:${(v.outputs.preview || {}).t || ""}:${(v.outputs.final || {}).t || ""}`;
  const statusChanged = key !== lastStatusKey; lastStatusKey = key;
  if ((!PLAN || PLAN_VID !== VID || (statusChanged && v.status === "plan_ready")) && !planDirty && !["new", "queued", "planning"].includes(v.status) && job.status === "ready") await loadPlan();
  if (statusChanged) { loadReports(); loadPreflight(); }
  await loadCompare();
  clearTimeout(pollTimer);
  if (anyBusy) pollTimer = setTimeout(() => refreshJob(), 1500);
}
function renderVariantTabs() {
  const vs = JOB.variants;
  $("#variantTabs").innerHTML = Object.entries(vs).map(([k, v]) => `<button class="vtab ${k === VID ? "active" : ""}" data-v="${k}">${esc(v.name)} <span class="st ${v.status}">${STATUS_TH[v.status] || v.status}</span></button>`).join("");
  $$("#variantTabs .vtab").forEach((b) => b.addEventListener("click", () => selectVariant(b.dataset.v)));
}
async function selectVariant(v) {
  if (planDirty && !confirm("มีการแก้แผนที่ยังไม่บันทึก ต้องการเปลี่ยนเวอร์ชันหรือไม่?")) return;
  VID = v; PLAN = null; planDirty = false; lastStatusKey = ""; await refreshJob();
}
function renderVariantPanel() {
  const v = JOB.variants[VID];
  const busy = ACTIVE.includes(v.status);
  $("#progBar").style.width = Math.round((v.progress || 0) * 100) + "%";
  $("#progMsg").textContent = `${STATUS_TH[v.status] || v.status}${v.message ? " — " + v.message : ""}`;
  ["#btnPreview", "#btnRender", "#btnRestyle", "#btnSavePlan", "#btnSavePreview"].forEach((b) => ($(b).disabled = busy || JOB.status !== "ready"));
  $("#btnCancel").classList.toggle("hidden", !busy || v.status === "planning");
  $("#btnDelVariant").classList.toggle("hidden", VID === "main");
  // style bar reflects the variant's own settings
  const st = (PLAN && PLAN_VID === VID && PLAN.settings) || {};
  if (document.activeElement && !document.activeElement.closest(".style-bar")) {
    $("#vPreset").value = v.preset_id || "";
    $("#vMode").value = (v.overrides || {}).mode || st.mode || "auto";
    $("#vDensity").value = (v.overrides || {}).density || st.density || 2;
    $("#vIntensity").value = (v.overrides || {}).intensity || st.intensity || "medium";
    $("#vProfile").value = (v.overrides || {}).export_profile || st.export_profile || "1080p_high";
  }
  const d = v.direction || (PLAN && PLAN.direction);
  $("#directionBox").innerHTML = d ? `<b>AI Director:</b> ${esc(d.summary)}${v.why ? `<br><span class="muted">เหตุผลของเวอร์ชันนี้: ${esc(v.why)}</span>` : ""}` : "";
  const o = v.outputs || {}; const base = `/api/jobs/${JOB.id}/files/`;
  const setVid = (el, out) => { const src = out ? `${base}${out.file}?t=${Math.round(out.t)}` : ""; if (el.dataset.src !== src) { el.dataset.src = src; el.src = src; } };
  setVid($("#vPreview"), o.preview); setVid($("#vFinal"), o.final);
  $("#previewInfo").textContent = o.preview ? `ความยาว ${o.preview.duration.toFixed(1)} วินาที · เรนเดอร์ ${o.preview.seconds}s${o.preview.reused_clips ? ` (ใช้ cache ${o.preview.reused_clips} คลิป)` : ""}` : "ยังไม่มี Preview";
  const staleNote = (x) => x && x.stale ? " · ⚠️ แผนถูกแก้หลังเรนเดอร์ — เรนเดอร์ใหม่เพื่อให้ตรงแผน" : "";
  $("#finalInfo").textContent = o.final ? `${o.final.size[0]}×${o.final.size[1]} · ${o.final.fps}fps · ${o.final.duration.toFixed(1)} วินาที · H.264/AAC · ${ENV.profiles[o.final.profile] || o.final.profile}${staleNote(o.final)}` : "ยังไม่ได้ Export";
  if (o.preview && o.preview.stale) $("#previewInfo").textContent += staleNote(o.preview);
  const dl = $("#btnDownload"); dl.classList.toggle("hidden", !o.final); if (o.final) dl.href = `${base}${o.final.file}?download=1`;
  const qc = (o.final || o.preview || {}).qc;
  const lvl = { error: "❌", warn: "⚠️", info: "ℹ️" };
  if (!qc) $("#qcList").innerHTML = '<li class="muted">ยังไม่มีผลตรวจ</li>';
  else {
    const errs = qc.filter((i) => i.level === "error").length;
    $("#qcList").innerHTML = `<li class="${errs ? "error" : "pass"}">${o.final ? "วิดีโอจริง" : "Preview"}: ${errs ? `พบข้อผิดพลาด ${errs} รายการ` : "✅ ผ่าน: เปิดเล่นได้, ไม่มีเฟรมดำ, เสียงไม่แตก, ซับซิงก์และอยู่ใน Safe Zone, กราฟิกไม่บังหน้า, ไฟล์เข้ากันได้"}</li>` +
      qc.map((i) => `<li class="${i.level}">${lvl[i.level] || ""} ${esc(i.message)}</li>`).join("");
  }
}
async function loadReports() {
  const o = JOB.variants[VID].outputs || {};
  const which = o.final ? "final" : o.preview ? "preview" : null;
  if (!which) { $("#fxReport").innerHTML = '<li class="muted">ยังไม่ได้เรนเดอร์</li>'; return; }
  try {
    const rep = await api(`/api/jobs/${JOB.id}/files/variants/${VID}/qc_${which}.json?t=${Date.now()}`);
    const rows = (rep.effects_report || []).filter((r) => r.effect !== "cache");
    const st = { rendered: "pass", fallback: "warn", failed: "error", adjusted: "info", reused: "info" };
    const th = { rendered: "เรนเดอร์จริง", fallback: "Fallback", failed: "ล้มเหลว", adjusted: "ปรับลด", reused: "cache" };
    $("#fxReport").innerHTML = (rows.length ? rows.map((r) => `<li class="${st[r.status] || ""}"><b>${esc(r.seg)} · ${esc(r.effect === "segmentation" ? "แยกตัวบุคคล" : fxName(r.effect))}</b> — ${th[r.status] || r.status}: ${esc(r.msg)}</li>`).join("") : '<li class="muted">ไม่มีเอฟเฟกต์ในเวอร์ชันนี้</li>') +
      `<li class="info">เสียง: ${rep.audio ? `${rep.audio.lufs} LUFS, true peak ${rep.audio.true_peak} dBFS` : "-"} · ใช้คลิปจาก cache ${rep.reused_clips || 0} คลิป · เวลาเรนเดอร์ ${rep.seconds}s</li>`;
  } catch { $("#fxReport").innerHTML = '<li class="muted">—</li>'; }
}
async function loadPreflight() {
  if (JOB.status !== "ready" || !["plan_ready", "preview_ready", "done", "cancelled", "error"].includes(JOB.variants[VID].status)) { $("#preflightBox").innerHTML = ""; return; }
  try {
    const p = await api(`/api/jobs/${JOB.id}/variants/${VID}/preflight?kind=final`);
    const apis = p.apis.map((a) => `${esc(a.name)}: ${a.available ? (a.allowed ? "อนุญาตแล้ว" : "มี แต่ไม่อนุญาต") : "ไม่มี"} — ${esc(a.when)}`).join("<br>");
    $("#preflightBox").innerHTML = `<b>ตรวจทรัพยากรก่อน Export</b><br>ประมาณเวลา ~${Math.max(1, Math.round(p.estimate_seconds / 6) / 10)} นาที${p.calibrated ? " (ปรับตามเครื่องนี้แล้ว)" : ""} · แยกตัวบุคคล ${p.mask_seconds}s · พื้นที่ว่าง ${p.disk_free_gb} GB (ต้องใช้ ~${p.disk_need_gb} GB) · คลิปใน cache ${p.cached_clips}<br>
      <span class="muted small">${apis}</span>${p.effect_fallbacks.length ? `<br><span class="warn-t">${p.effect_fallbacks.map(esc).join("<br>")}</span>` : ""}${p.errors.length ? `<br><span class="err-t">${p.errors.map(esc).join("<br>")}</span>` : ""}`;
  } catch (e) { $("#preflightBox").innerHTML = ""; }
}
function renderAssets(job) {
  const roleTh = { broll: "ภาพประกอบ", reference: "อ้างอิง", music: "เพลง", transcript: "Transcript" };
  const srcTh = { user: "ของฉัน", stock: "Stock", ai: "AI" };
  const a = job.assets || [];
  const html = a.length ? a.map((x) => {
    const url = `/api/jobs/${job.id}/files/assets/${encodeURIComponent(x.name)}`;
    const th = x.kind === "image" ? `<img src="${url}" alt="">` : `<div class="ph">${x.kind === "video" ? "🎬" : x.kind === "audio" ? "🎵" : "📄"}</div>`;
    return `<div class="asset">${th}<div><div>${esc(x.name)}</div><span class="badge">${roleTh[x.role] || x.role}</span><span class="badge">${srcTh[x.source] || x.source}</span></div></div>`;
  }).join("") : '<div class="muted small">ไม่มีไฟล์ประกอบ</div>';
  if ($("#assetList").dataset.h !== html) { $("#assetList").innerHTML = html; $("#assetList").dataset.h = html; }
}
$("#btnAddAssets").addEventListener("click", async () => {
  const files = $("#fMoreAssets").files; if (!files.length) return toast("เลือกไฟล์ก่อน", true);
  const fd = new FormData(); [...files].forEach((f) => fd.append("files", f));
  fd.append("role", $("#moreRole").value); fd.append("source", $("#moreSource").value);
  try { await api(`/api/jobs/${JOB.id}/assets`, { method: "POST", body: fd }); toast("เพิ่มไฟล์แล้ว"); $("#fMoreAssets").value = ""; await refreshJob(); if (PLAN) renderPlan(); }
  catch (e) { toast(e.message, true); }
});
async function vAction(name, body) {
  try { await api(`/api/jobs/${JOB.id}/variants/${VID}/${name}`, { method: "POST", json: body || {} }); lastStatusKey = ""; refreshJob(); }
  catch (e) { toast(e.message, true); }
}
$("#btnReanalyze").addEventListener("click", async () => {
  if (!confirm("วิเคราะห์ใหม่จะถอดเสียง/ตรวจใบหน้าใหม่ และสร้างแผนทุกเวอร์ชันใหม่ ต่อหรือไม่?")) return;
  try { await api(`/api/jobs/${JOB.id}/analyze`, { method: "POST" }); PLAN = null; planDirty = false; refreshJob(); } catch (e) { toast(e.message, true); }
});
$("#btnPreview").addEventListener("click", async () => { if (planDirty && !(await savePlan())) return; vAction("preview"); });
$("#btnRender").addEventListener("click", async () => {
  if (planDirty && !(await savePlan())) return;
  const p = await api(`/api/jobs/${JOB.id}/variants/${VID}/preflight?kind=final`).catch(() => null);
  if (p && p.apis.some((a) => a.allowed && a.available && a.when !== "ไม่ถูกเรียก") && !confirm("เวอร์ชันนี้อาจเรียก API ที่มีค่าใช้จ่าย ต่อหรือไม่?")) return;
  vAction("render");
});
$("#btnCancel").addEventListener("click", () => vAction("cancel"));
$("#btnDelVariant").addEventListener("click", async () => {
  if (!confirm(`ลบเวอร์ชัน "${JOB.variants[VID].name}" และไฟล์ของเวอร์ชันนี้?`)) return;
  try { await api(`/api/jobs/${JOB.id}/variants/${VID}`, { method: "DELETE" }); VID = "main"; PLAN = null; refreshJob(); } catch (e) { toast(e.message, true); }
});
$("#btnRestyle").addEventListener("click", async () => {
  if (planDirty && !confirm("การเปลี่ยนสไตล์จะสร้างแผนใหม่ (คงข้อความ/การตัดที่คุณแก้ไว้) แต่การแก้เอฟเฟกต์ด้วยมือจะถูกแทนที่ ต่อหรือไม่?")) return;
  const body = { mode: $("#vMode").value, density: +$("#vDensity").value, intensity: $("#vIntensity").value, export_profile: $("#vProfile").value };
  if ($("#vPreset").value) body.preset_id = $("#vPreset").value;
  if (body.preset_id) { const p = PRESETS.find((x) => x.id === body.preset_id); if (p) { body.mode = $("#vMode").value || p.mode; } }
  try { await api(`/api/jobs/${JOB.id}/variants/${VID}/restyle`, { method: "POST", json: body }); planDirty = false; PLAN = null; toast("กำลังสร้างแผนใหม่จากผลวิเคราะห์เดิม (ไม่ถอดเสียงใหม่)"); refreshJob(); }
  catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- variations + comparison
$("#btnVariations").addEventListener("click", () => {
  $("#varChoices").innerHTML = Object.entries(ENV.variations).map(([k, v]) => `<label class="var-choice"><input type="checkbox" value="${k}" ${["clean", "cinematic", "retention"].includes(k) ? "checked" : ""} ${JOB.variants[k] ? "" : ""}><div><b>${esc(v.name)}</b>${JOB.variants[k] ? ' <span class="badge">มีแล้ว — จะสร้างแผนใหม่</span>' : ""}<div class="muted small">${esc(v.why)}</div></div></label>`).join("");
  $("#varDialog").showModal();
});
$("#varDialog").addEventListener("close", async () => {
  if ($("#varDialog").returnValue !== "ok") return;
  const kinds = $$("#varChoices input:checked").map((i) => i.value);
  if (!kinds.length) return toast("เลือกอย่างน้อย 1 เวอร์ชัน", true);
  try { await api(`/api/jobs/${JOB.id}/variations`, { method: "POST", json: { kinds, render: $("#varPreview").checked ? "preview" : "none" } }); toast(`เข้าคิว ${kinds.length} เวอร์ชันแล้ว — ทำทีละเวอร์ชันตามลำดับ`); refreshJob(); }
  catch (e) { toast(e.message, true); }
});
async function loadCompare() {
  let c; try { c = await api(`/api/jobs/${JOB.id}/compare`); } catch { return; }
  CMP = c;
  $("#compareCard").classList.toggle("hidden", c.variants.length < 2);
  const segSel = $("#cmpSeg");
  if (segSel.options.length !== c.segments.length) segSel.innerHTML = c.segments.map((s) => `<option value="${s.id}">${fmt(s.start)} ${esc(s.text.slice(0, 40))}</option>`).join("");
  $("#cmpTable tbody").innerHTML = c.variants.map((v) => {
    const s = v.stats || {}; const busy = ACTIVE.includes(v.status);
    const out = v.outputs || {};
    return `<tr class="${v.id === VID ? "sel" : ""}"><td><b>${esc(v.name)}</b><div class="muted small">${esc(v.preset || "")}</div></td>
      <td>${s.duration ? fmt(s.duration) : "-"}</td><td>${esc(s.subtitle_mode === "karaoke" ? "ไฮไลต์ทีละคำ" : "เน้นคำ")}<div class="muted small">${esc(s.subtitle_font || "")}</div></td>
      <td>${(s.main_effects || []).map((e) => `<span class="chip">${esc(e)}</span>`).join(" ") || '<span class="muted">ซับ + การตัด</span>'}</td>
      <td>${s.broll_segments ?? "-"}</td><td>${s.mograph_segments ?? "-"}</td><td>${s.transitions ?? "-"}</td>
      <td><span class="st ${v.status}">${STATUS_TH[v.status] || v.status}</span>${busy ? ` ${Math.round((v.progress || 0) * 100)}%` : ""}${v.qc_errors ? ` <span class="err-t">QC ${v.qc_errors}</span>` : ""}</td>
      <td class="nowrap"><button class="ghost sm" data-sel="${v.id}">เลือก</button>
        <button class="ghost sm" data-prev="${v.id}" ${busy || !s.duration ? "disabled" : ""}>Preview</button>
        <button class="primary sm" data-exp="${v.id}" ${busy || !s.duration ? "disabled" : ""}>Export</button>
        ${out.final ? `<a class="ghost sm" href="/api/jobs/${JOB.id}/files/${out.final.file}?download=1" title="${out.final.stale ? "ไฟล์นี้เรนเดอร์จากแผนก่อนหน้า" : "ดาวน์โหลด"}">⬇${out.final.stale ? " (เก่า)" : ""}</a>` : ""}</td></tr>`;
  }).join("");
  $$("[data-sel]").forEach((b) => b.onclick = () => selectVariant(b.dataset.sel));
  $$("[data-prev]").forEach((b) => b.onclick = async () => { VID = b.dataset.prev; PLAN = null; await vAction("preview"); });
  $$("[data-exp]").forEach((b) => b.onclick = async () => { VID = b.dataset.exp; PLAN = null; await vAction("render"); });
  const players = c.variants.filter((v) => v.outputs.preview || v.outputs.final);
  const html = players.map((v) => { const o = v.outputs.final || v.outputs.preview; return `<figure data-v="${v.id}"><figcaption>${esc(v.name)}</figcaption><video src="/api/jobs/${JOB.id}/files/${o.file}?t=${Math.round(o.t)}" controls playsinline preload="metadata"></video></figure>`; }).join("");
  if ($("#cmpPlayers").dataset.h !== html) { $("#cmpPlayers").innerHTML = html; $("#cmpPlayers").dataset.h = html; }
}
function seekCompare(play) {
  const sid = $("#cmpSeg").value;
  $$("#cmpPlayers figure").forEach((f) => {
    const v = CMP.variants.find((x) => x.id === f.dataset.v); const vid = $("video", f);
    const t = v && v.seg_at[sid];
    if (t === undefined) { vid.pause(); f.classList.add("missing"); return; }
    f.classList.remove("missing"); vid.currentTime = t + 0.05; if (play) vid.play().catch(() => {}); else vid.pause();
  });
}
$("#cmpSeg").addEventListener("change", () => seekCompare(false));
$("#btnCmpPlay").addEventListener("click", () => seekCompare(true));

// ---------------------------------------------------------------- plan editor (timeline + effect map)
async function loadPlan() {
  try { PLAN = await api(`/api/jobs/${JOB.id}/variants/${VID}/plan`); PLAN_VID = VID; planDirty = false; renderPlan(); renderVariantPanel(); } catch { /* not yet */ }
}
function brollFields(b, assets) {
  const k = b.kind || "none";
  const inp = (f, ph, v) => `<input type="text" data-b="${f}" placeholder="${ph}" value="${esc(v ?? "")}">`;
  switch (k) {
    case "stat": return inp("value", "ตัวเลข", b.value) + inp("unit", "หน่วย", b.unit) + inp("caption", "คำอธิบาย", b.caption);
    case "timeline": return inp("year", "ปี", b.year) + inp("caption", "คำอธิบาย", b.caption);
    case "steps": return `<textarea data-b="items" placeholder="หนึ่งขั้นตอนต่อบรรทัด">${esc((b.items || []).join("\n"))}</textarea>`;
    case "keyword": return inp("text", "คำสำคัญ", b.text);
    case "compare": return inp("left", "ฝั่งซ้าย", b.left) + inp("right", "ฝั่งขวา", b.right);
    case "placeholder": return `<textarea data-b="description" placeholder="ภาพที่ต้องสร้าง">${esc(b.description)}</textarea>` + inp("prompt", "AI prompt", b.prompt);
    case "asset": {
      const list = assets.filter((a) => a.role === "broll");
      if (!list.length) return '<div class="note">ยังไม่มีไฟล์ภาพประกอบ</div>';
      return `<select data-b="asset">${list.map((a) => `<option value="${esc(a.name)}" ${a.name === b.asset ? "selected" : ""}>${esc(a.name)} (${a.source})</option>`).join("")}</select>`;
    }
    default: return "";
  }
}
function effectChips(s) {
  return (s.effects || []).map((e, i) => {
    const meta = ENV.effects.find((x) => x.id === e.id) || { params: [], name: e.id, implementation: "real" };
    const imp = IMPL_TH[meta.implementation];
    const params = meta.params.map((p) => {
      const v = (e.params || {})[p.name] ?? p.default;
      if (p.type === "choice") return `<label>${esc(p.label || p.name)}<select data-p="${p.name}">${p.choices.map((c) => `<option ${c === v ? "selected" : ""}>${c}</option>`).join("")}</select></label>`;
      if (p.type === "bool") return `<label class="chk"><input type="checkbox" data-p="${p.name}" ${v ? "checked" : ""}> ${esc(p.label || p.name)}</label>`;
      return `<label>${esc(p.label || p.name)}<input type="number" step="any" data-p="${p.name}" value="${v}" ${p.min !== null ? `min="${p.min}"` : ""} ${p.max !== null ? `max="${p.max}"` : ""}></label>`;
    }).join("");
    return `<div class="fx" data-i="${i}" data-id="${e.id}"><div class="fx-head"><b>${esc(meta.name)}</b> <span class="impl ${imp[1]}">${imp[0]}</span>
      ${e.auto ? '<span class="badge">AI</span>' : '<span class="badge">ผู้ใช้</span>'}<button class="x" title="ยกเลิกเอฟเฟกต์นี้" data-rm="${i}">✕</button></div>
      <div class="muted small">เหตุผล: ${esc(e.reason || "-")}</div>${params ? `<details><summary class="small">พารามิเตอร์</summary><div class="fx-params">${params}</div></details>` : ""}</div>`;
  }).join("");
}
function renderPlan() {
  if (!PLAN) return;
  const segs = PLAN.segments, src = PLAN.source;
  const kept = segs.filter((s) => s.keep);
  const nfx = kept.reduce((n, s) => n + (s.effects || []).length, 0);
  $("#planSummary").textContent = `· ${segs.length} ประโยค (ตัด ${segs.length - kept.length}) · ${fmt(src.duration)} → ~${fmt(PLAN.estimated_duration)} · เอฟเฟกต์ ${nfx} จุด · STT: ${PLAN.analysis?.asr?.engine || "-"} · AI วิเคราะห์เรื่อง: ${PLAN.analysis?.llm ? "Claude" : "heuristic"}`;
  const total = src.duration || 1;
  let html = "", last = 0;
  segs.forEach((s) => {
    if (s.start > last) html += `<div class="cut" style="flex:${s.start - last}" title="ช่วงเงียบ"></div>`;
    const fx = (s.effects || []).length ? "◆" : "";
    html += `<div class="${s.keep ? s.layout : "cut"}" style="flex:${Math.max(0.05, s.end - s.start)}" data-id="${s.id}" title="${esc(fmt(s.start) + " " + s.text + " " + (s.effects || []).map((e) => fxName(e.id)).join(", "))}">${s.keep ? fx : ""}</div>`;
    last = Math.max(last, s.end);
  });
  if (total > last) html += `<div class="cut" style="flex:${total - last}"></div>`;
  $("#timelineStrip").innerHTML = html;
  $$("#timelineStrip [data-id]").forEach((d) => d.addEventListener("click", () => {
    const tr = $(`#planTable tr[data-id="${d.dataset.id}"]`); tr.scrollIntoView({ behavior: "smooth", block: "center" });
    tr.classList.add("flash"); setTimeout(() => tr.classList.remove("flash"), 1200);
  }));
  const assets = JOB.assets || [];
  const fxOptions = ENV.effects.filter((e) => e.category !== "transition").map((e) => `<option value="${e.id}">${String(e.number).padStart(2, "0")} ${esc(e.name)}${e.implementation === "simulation" ? " (จำลอง)" : ""}</option>`).join("");
  $("#planTable tbody").innerHTML = segs.map((s) => {
    const b = s.broll || { kind: "none" };
    const notes = [];
    if (!s.keep && s.cut_reason) notes.push(`<div class="cutreason">✂ ${esc(s.cut_reason)}</div>`);
    if (s.spelling?.length) notes.push(`<div class="note">ตรวจคำ: ${esc(s.spelling.join(", "))}</div>`);
    const eb = s.effect_budget ? `<div class="muted small">ความสำคัญ ${s.effect_budget.importance} · budget ${s.effect_budget.used}/${s.effect_budget.budget}</div>` : "";
    const ti = s.transition_in || { id: "cut" };
    return `<tr data-id="${s.id}" class="${s.keep ? "" : "is-cut" + ($("#showCut").checked ? "" : " hide")}">
      <td class="tcell"><b>${fmt(s.start)}</b><br>${fmt(s.end)}<br><span class="role ${s.role || ""}">${ROLE_TH[s.role] || "—"}</span>${eb}</td>
      <td><img class="thumb" src="/api/jobs/${JOB.id}/files/thumbs/${s.id}.jpg" alt="" loading="lazy" onerror="this.style.display='none'"></td>
      <td><input type="checkbox" data-f="keep" ${s.keep ? "checked" : ""} title="เก็บประโยคนี้"></td>
      <td style="min-width:260px"><textarea data-f="text">${esc(s.text)}</textarea>
        <input type="text" data-f="highlight" placeholder="คำที่เน้นสี (คั่นด้วย ,)" value="${esc((s.highlight || []).join(", "))}">
        <div class="subs">${(s.subs || []).map((p) => `<span>${p.parts.map((w) => (w.hl ? `<em>${esc(w.w)}</em>` : esc(w.w))).join("")}</span>`).join("")}</div>${notes.join("")}</td>
      <td><div class="stack"><label>Layout</label><select data-f="layout">${opt(LAYOUT_TH, s.layout)}</select>
        <label>ระดับภาพ</label><select data-f="zoom">${opt(ZOOM_TH, s.zoom)}</select>
        <label>กราฟิกพื้นฐาน</label><select data-f="bkind">${opt(BROLL_TH, b.kind)}</select><div class="bfields">${brollFields(b, assets)}</div>
        <label>Title Card</label><input type="text" data-f="title" value="${esc(s.title || "")}" placeholder="(ไม่มี)"></div></td>
      <td style="min-width:240px"><div class="fx-list">${effectChips(s) || '<div class="muted small">ไม่มีเอฟเฟกต์ (ผู้พูด + ซับ)</div>'}</div>
        ${s.keep ? `<select data-add><option value="">+ เพิ่มเอฟเฟกต์…</option>${fxOptions}</select>` : ""}</td>
      <td><div class="stack"><label>Transition เข้า</label><select data-f="trans">${opt(TRANS_TH, ti.id)}</select>
        <div class="muted small">${ti.id !== "cut" ? esc(ti.reason || "") : ""}</div>
        <label>Sound Effect</label><select data-f="sfx">${opt(SFX_TH, s.sfx || "none")}</select>
        <div class="muted small">ซับ: ${PLAN.settings.subtitle_mode === "karaoke" ? "ไฮไลต์ทีละคำ" : "เน้นคำ"}</div></div></td></tr>`;
  }).join("");
  $$("#planTable tbody tr").forEach((tr) => {
    const seg = segs.find((x) => x.id === tr.dataset.id);
    tr.addEventListener("input", () => (planDirty = true));
    tr.addEventListener("change", (e) => {
      planDirty = true;
      const t = e.target;
      if (t.dataset.f === "bkind") { collectRow(tr, seg); seg.broll = { ...defaultBroll(t.value, seg), kind: t.value }; if (t.value !== "none" && ["full", "fit"].includes(seg.layout)) seg.layout = "pip"; if (t.value === "none" && ["pip", "split", "broll_full"].includes(seg.layout) && !(seg.effects || []).some((x) => (ENV.effects.find((m) => m.id === x.id) || {}).category === "panel")) seg.layout = "full"; renderPlan(); planDirty = true; }
      if (t.matches("[data-add]") && t.value) {
        collectRow(tr, seg);
        const meta = ENV.effects.find((m) => m.id === t.value);
        const params = Object.fromEntries(meta.params.map((p) => [p.name, p.default]));
        seg.effects = [...(seg.effects || []), { id: t.value, params, reason: "ผู้ใช้เลือกเอง", auto: false }];
        if (meta.layout === "pip") seg.layout = "pip"; else if (meta.layout === "full") seg.layout = "full";
        renderPlan(); planDirty = true;
      }
      if (t.dataset.f === "keep") tr.classList.toggle("is-cut", !t.checked);
    });
    $$("[data-rm]", tr).forEach((b) => b.addEventListener("click", () => { collectRow(tr, seg); seg.effects.splice(+b.dataset.rm, 1); renderPlan(); planDirty = true; }));
  });
}
function defaultBroll(kind, seg) {
  const hl = (seg.highlight || [])[0] || "";
  return { stat: { value: "", unit: "", caption: "" }, steps: { items: [] }, timeline: { year: "", caption: "" }, keyword: { text: hl },
    compare: { left: "", right: "" }, placeholder: { description: "", prompt: "", label: "ภาพจำลอง / ภาพประกอบ" },
    asset: { asset: (JOB.assets || []).find((a) => a.role === "broll")?.name || "" } }[kind] || {};
}
function collectRow(tr, seg) {
  const f = (n) => $(`[data-f="${n}"]`, tr);
  seg.keep = f("keep").checked; seg.text = f("text").value.trim();
  seg.highlight = f("highlight").value.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  seg.layout = f("layout").value; seg.zoom = f("zoom").value; seg.title = f("title").value.trim(); seg.sfx = f("sfx").value;
  const tid = f("trans").value;
  seg.transition_in = tid === (seg.transition_in || {}).id ? seg.transition_in : { id: tid, reason: "ผู้ใช้เลือกเอง" };
  const kind = f("bkind").value; const b = { ...(seg.broll || {}), kind };
  $$("[data-b]", tr).forEach((el) => { b[el.dataset.b] = el.dataset.b === "items" ? el.value.split("\n").map((x) => x.trim()).filter(Boolean) : el.value; });
  if (kind === "steps") b.word_index = (seg.broll?.word_index || []).slice(0, (b.items || []).length);
  if (kind === "asset") { const a = (JOB.assets || []).find((x) => x.name === b.asset); b.source = a?.source || "user"; b.label = a?.source === "ai" ? "ภาพสร้างด้วย AI" : a?.source === "stock" ? "ภาพประกอบ (Stock)" : "ภาพประกอบ"; }
  seg.broll = b;
  $$(".fx", tr).forEach((el) => {
    const e = seg.effects[+el.dataset.i]; if (!e) return;
    $$("[data-p]", el).forEach((inp) => { e.params = e.params || {}; e.params[inp.dataset.p] = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? parseFloat(inp.value) : inp.value; });
  });
}
async function savePlan() {
  if (!PLAN) return false;
  $$("#planTable tbody tr").forEach((tr) => collectRow(tr, PLAN.segments.find((s) => s.id === tr.dataset.id)));
  try {
    PLAN = await api(`/api/jobs/${JOB.id}/variants/${VID}/plan`, { method: "PUT", json: PLAN });
    planDirty = false; renderPlan(); toast("บันทึกแผนแล้ว"); return true;
  } catch (e) { toast(e.message, true); return false; }
}
$("#btnSavePlan").addEventListener("click", () => savePlan());
$("#btnSavePreview").addEventListener("click", async () => { if (await savePlan()) vAction("preview"); });
$("#showCut").addEventListener("change", () => $$("#planTable tr.is-cut").forEach((tr) => tr.classList.toggle("hide", !$("#showCut").checked)));
window.addEventListener("beforeunload", (e) => { if (planDirty) { e.preventDefault(); e.returnValue = ""; } });

// ---------------------------------------------------------------- preset manager
let PE = null;
function renderPresetList() {
  $("#presetList").innerHTML = PRESETS.map((p) => `<button class="preset-item ${PE && PE.id === p.id ? "active" : ""}" data-id="${p.id}">
    <span class="sw" style="background:${p.accent || "#555"}"></span><span class="sw" style="background:${p.accent2 || "#555"}"></span>
    <span>${esc(p.name)}</span>${p.builtin ? '<span class="badge">ในตัว</span>' : '<span class="badge my">ของฉัน</span>'}</button>`).join("");
  $$("#presetList .preset-item").forEach((b) => b.addEventListener("click", () => editPreset(PRESETS.find((p) => p.id === b.dataset.id))));
}
function editPreset(p, isNew = false) {
  PE = isNew ? { ...p, id: null, builtin: false } : p;
  renderPresetList();
  const ro = PE.builtin;
  $("#peTitle").textContent = isNew ? "Preset ใหม่" : PE.name;
  const fx = ENV.effects.filter((e) => e.category !== "transition");
  const fxState = (id) => (PE.banned_effects || []).includes(id) ? "ban" : (PE.allowed_effects || []).includes(id) ? "allow" : "";
  const sel = (n, map, v) => `<select name="${n}" ${ro ? "disabled" : ""}>${opt(map, v)}</select>`;
  $("#peBody").className = "";
  $("#peBody").innerHTML = `${ro ? '<div class="note">Preset ในตัวแก้ไขไม่ได้ — กด "ทำสำเนา" เพื่อสร้างเวอร์ชันของคุณ</div>' : ""}
    <div class="settings pe">
      <div class="field wide"><label>ชื่อสไตล์</label><input type="text" name="name" value="${esc(PE.name)}" maxlength="60" ${ro ? "disabled" : ""}></div>
      <div class="field wide"><label>คำอธิบาย</label><input type="text" name="description" value="${esc(PE.description || "")}" maxlength="400" ${ro ? "disabled" : ""}></div>
      <div class="field"><label>สีหลัก / สีรอง <span class="opt">ว่าง = ใช้สีแบรนด์ของโปรเจกต์</span></label><div class="row">
        <input type="color" name="accent" value="${PE.accent || "#BC0000"}" ${ro ? "disabled" : ""}><input type="color" name="accent2" value="${PE.accent2 || "#A8CE20"}" ${ro ? "disabled" : ""}>
        <label class="chk"><input type="checkbox" name="use_brand" ${!PE.accent ? "checked" : ""} ${ro ? "disabled" : ""}> ใช้สีแบรนด์โปรเจกต์</label></div></div>
      <div class="field"><label>ฟอนต์ซับ</label>${sel("subtitle_font", Object.fromEntries(ENV.fonts.map((f) => [f, f])), PE.subtitle_font)}</div>
      <div class="field"><label>รูปแบบซับ</label>${sel("subtitle_mode", { keyword: "เน้นคำสำคัญ", karaoke: "ไฮไลต์ทีละคำ" }, PE.subtitle_mode)}</div>
      <div class="field"><label>ขนาดซับ</label><input type="number" name="subtitle_size" min="60" max="130" value="${PE.subtitle_size}" ${ro ? "disabled" : ""}></div>
      <div class="field"><label>โหมดตัดต่อ</label>${sel("mode", Object.fromEntries(Object.entries(ENV.modes).map(([k, m]) => [k, m.name])), PE.mode)}</div>
      <div class="field"><label>ความหนาแน่น</label>${sel("density", Object.fromEntries(Object.entries(ENV.densities).map(([k, d]) => [k, `${k} ${d.name}`])), PE.density)}</div>
      <div class="field"><label>ความเข้มข้น Motion Graphics</label>${sel("intensity", { low: "LOW", medium: "MEDIUM", high: "HIGH" }, PE.intensity)}</div>
      <div class="field"><label>จังหวะตัด</label>${sel("pacing", { calm: "ช้า", normal: "ปกติ", fast: "เร็ว" }, PE.pacing)}</div>
      <div class="field"><label>เพลง</label>${sel("music", { generated: "สร้างเอง", upload: "ไฟล์ที่อัปโหลด", none: "ไม่มี" }, PE.music)}</div>
      <div class="field"><label>Aspect Ratio</label>${sel("aspect", Object.fromEntries(ENV.aspects.map((a) => [a, a])), PE.aspect)}<div class="muted small">ขณะนี้รองรับ 9:16 เท่านั้น</div></div>
      <div class="field"><label>Export Profile</label>${sel("export_profile", ENV.profiles, PE.export_profile)}</div>
      <div class="checks"><label class="chk"><input type="checkbox" name="sfx" ${PE.sfx ? "checked" : ""} ${ro ? "disabled" : ""}> Sound Design / SFX</label>
        <label class="chk"><input type="checkbox" name="title_cards" ${PE.title_cards ? "checked" : ""} ${ro ? "disabled" : ""}> Title Card</label>
        ${ENV.transitions.map((t) => `<label class="chk"><input type="checkbox" name="tr_${t}" ${(PE.transitions || []).includes(t) ? "checked" : ""} ${ro ? "disabled" : ""}> ${TRANS_TH[t]}</label>`).join("")}</div>
    </div>
    <h3>เอฟเฟกต์ที่อนุญาต / ห้ามใช้ <span class="muted small">(ถ้าเลือก "อนุญาต" อย่างน้อยหนึ่งตัว ระบบจะใช้เฉพาะตัวที่อนุญาต)</span></h3>
    <div class="fx-perm">${fx.map((e) => `<label><span>${String(e.number).padStart(2, "0")} ${esc(e.name)}</span><select data-fx="${e.id}" ${ro ? "disabled" : ""}>
      <option value="" ${fxState(e.id) === "" ? "selected" : ""}>ตาม AI</option><option value="allow" ${fxState(e.id) === "allow" ? "selected" : ""}>อนุญาต</option><option value="ban" ${fxState(e.id) === "ban" ? "selected" : ""}>ห้ามใช้</option></select></label>`).join("")}</div>
    <div class="row pe-actions">
      ${ro ? "" : `<button class="primary" id="peSave">${isNew ? "สร้าง Preset" : "บันทึก"}</button>`}
      ${isNew ? "" : `<button class="ghost" id="peDup">ทำสำเนา</button>`}
      ${!ro && !isNew ? `<button class="ghost" id="peRename">เปลี่ยนชื่อ</button><button class="ghost danger" id="peDel">ลบ</button>` : ""}
      <button class="ghost" id="peUse">ใช้กับงานใหม่</button>
    </div><div id="peErr" class="err-t"></div>`;
  const read = () => {
    const g = (n) => $(`#peBody [name=${n}]`);
    const useBrand = g("use_brand").checked;
    const d = { name: g("name").value, description: g("description").value, accent: useBrand ? null : g("accent").value, accent2: useBrand ? null : g("accent2").value,
      subtitle_font: g("subtitle_font").value, subtitle_mode: g("subtitle_mode").value, subtitle_size: +g("subtitle_size").value, mode: g("mode").value,
      density: +g("density").value, intensity: g("intensity").value, pacing: g("pacing").value, music: g("music").value, aspect: g("aspect").value,
      export_profile: g("export_profile").value, sfx: g("sfx").checked, title_cards: g("title_cards").checked,
      transitions: ENV.transitions.filter((t) => g("tr_" + t).checked),
      allowed_effects: $$("#peBody [data-fx]").filter((s) => s.value === "allow").map((s) => s.dataset.fx),
      banned_effects: $$("#peBody [data-fx]").filter((s) => s.value === "ban").map((s) => s.dataset.fx) };
    return { ...PE, ...d };
  };
  const done = async (p, msg) => { await loadPresets(); PE = PRESETS.find((x) => x.id === p.id) || p; editPreset(PE); toast(msg); };
  const fail = (e) => { $("#peErr").textContent = "บันทึกไม่สำเร็จ: " + e.message; toast("บันทึกไม่สำเร็จ", true); };
  $("#peSave")?.addEventListener("click", async () => {
    try { const p = isNew ? await api("/api/presets", { method: "POST", json: read() }) : await api(`/api/presets/${PE.id}`, { method: "PUT", json: read() }); await done(p, `บันทึก "${p.name}" ลง data/presets.json แล้ว`); } catch (e) { fail(e); }
  });
  $("#peDup")?.addEventListener("click", async () => { const name = prompt("ชื่อสำเนา", `${PE.name} (สำเนา)`); if (!name) return; try { await done(await api(`/api/presets/${PE.id}/duplicate`, { method: "POST", json: { name } }), "ทำสำเนาแล้ว"); } catch (e) { fail(e); } });
  $("#peRename")?.addEventListener("click", async () => { const name = prompt("ชื่อใหม่", PE.name); if (!name) return; try { await done(await api(`/api/presets/${PE.id}/rename`, { method: "POST", json: { name } }), "เปลี่ยนชื่อแล้ว"); } catch (e) { fail(e); } });
  $("#peDel")?.addEventListener("click", async () => { if (!confirm(`ลบ Preset "${PE.name}"?`)) return; try { await api(`/api/presets/${PE.id}`, { method: "DELETE" }); PE = null; await loadPresets(); renderPresetList(); $("#peBody").innerHTML = "ลบแล้ว"; toast("ลบ Preset แล้ว"); } catch (e) { fail(e); } });
  $("#peUse")?.addEventListener("click", () => { if (!PE.id) return toast("บันทึกก่อน", true); $("#presetSel").value = PE.id; applyPreset(PE); show("new"); });
}
$("#btnNewPreset").addEventListener("click", () => editPreset({ ...PRESETS[0], name: "สไตล์ใหม่", description: "", accent: null, accent2: null, builtin: false }, true));

// ---------------------------------------------------------------- effects catalogue
function renderEffects() {
  $("#effectGrid").innerHTML = ENV.effects.map((e) => {
    const imp = IMPL_TH[e.implementation];
    return `<div class="effect-card"><div class="fx-num">${String(e.number).padStart(2, "0")}</div><h3>${esc(e.name)} <span class="muted small">${esc(e.name_th)}</span></h3>
      <span class="impl ${imp[1]}">${imp[0]}</span> ${e.available ? "" : '<span class="impl api">ไม่พร้อม</span>'} ${e.degraded ? `<span class="impl sim">${esc(e.degraded_reason)}</span>` : ""}
      <p>${esc(e.note)}</p>
      <div class="muted small"><b>Input:</b> ${esc(e.inputs.join(", ") || "-")}<br><b>Fallback:</b> ${esc(e.fallback || "-")}<br><b>ต้องการ:</b> ${esc([...e.requires, ...e.enhanced_by.map((x) => x + " (ช่วยให้ดีขึ้น)")].join(", ") || "FFmpeg เท่านั้น")}
      ${e.params.length ? `<br><b>พารามิเตอร์:</b> ${e.params.map((p) => esc(p.label || p.name)).join(", ")}` : ""}</div></div>`;
  }).join("");
}

// ---------------------------------------------------------------- history
async function loadHistory() {
  const list = await api(`/api/jobs?project=${PROJECT}`);
  $("#historyList").innerHTML = list.length ? list.map((j) => `<div class="history-item"><div><b>${esc(j.title)}</b>
    <div class="muted small">${new Date(j.created * 1000).toLocaleString("th-TH")} · ${STATUS_TH[j.status] || j.status} · ${Object.values(j.variants).map((v) => `${esc(v.name)}: ${STATUS_TH[v.status] || v.status}`).join(" · ")}</div></div>
    <div class="actions">${Object.entries(j.variants).filter(([, v]) => v.outputs.final).map(([k, v]) => `<a class="ghost sm" href="/api/jobs/${j.id}/files/${v.outputs.final.file}?download=1">⬇ ${esc(v.name)}</a>`).join("")}
    <button class="ghost" data-open="${j.id}">เปิด</button></div></div>`).join("") : '<div class="muted">ยังไม่มีงานในโปรเจกต์นี้</div>';
  $$("[data-open]").forEach((b) => b.addEventListener("click", () => openJob(b.dataset.open)));
}

(async () => {
  try { await loadEnv(); await loadPresets(); await loadProjects(); applyMemory(); }
  catch (e) { $("#envList").textContent = "ติดต่อเซิร์ฟเวอร์ไม่ได้: " + e.message; return; }
  const m = location.hash.match(/job=([a-f0-9]{12})/);
  if (m) openJob(m[1]);
})();
window.addEventListener("hashchange", () => {
  const m = location.hash.match(/job=([a-f0-9]{12})/);
  if (m && (!JOB || JOB.id !== m[1])) openJob(m[1]);
});
