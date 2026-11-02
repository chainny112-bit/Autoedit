// Render assets/characters/animated_character.svg into looping transparent VP9 sprites (one per shirt colour /
// pose) for tools/land_transfer_animation.py. The CSS animation is stepped frame by frame in Chromium, so the
// sprite moves exactly like the SVG. Needs Node + Playwright + FFmpeg — only to regenerate; the sprites are
// committed in assets/characters/sprites/.
//
// Usage: node tools/render_character_sprites.js
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SVG = fs.readFileSync(path.join(ROOT, 'assets/characters/animated_character.svg'), 'utf8');
const OUT = path.join(ROOT, 'assets/characters/sprites');
const FPS = 30, LOOP_S = 6;          // 6 s = whole cycles of float (3 s), wave (1.2 s) and hair (3 s)
const VIEW = [200, 150, 440, 590];   // crop of the 800x800 viewBox around the character + its shadow
const PX_H = 590;                    // sprite height in px (1 px per viewBox unit)

// name -> shirt gradient (light, dark), trousers, waving?
const VARIANTS = {
  red_wave: ['#ff555b', '#bd142b', '#293449', true], red_idle: ['#ff555b', '#bd142b', '#293449', false],
  blue_wave: ['#5f97ea', '#2a57a6', '#293449', true], blue_idle: ['#5f97ea', '#2a57a6', '#293449', false],
  teal_wave: ['#43c6b2', '#1d7c6f', '#3b3f4a', true], teal_idle: ['#43c6b2', '#1d7c6f', '#3b3f4a', false],
  navy_wave: ['#46669c', '#1c3157', '#23262e', true], navy_idle: ['#46669c', '#1c3157', '#23262e', false],
  lime_idle: ['#c6e255', '#7c9c12', '#3b3f4a', false],
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: VIEW[2], height: PX_H } });
  for (const [name, [s1, s2, pants, wave]] of Object.entries(VARIANTS)) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sprite-'));
    let svg = SVG.replace(/viewBox="[^"]*"/, `viewBox="${VIEW.join(' ')}"`)
      .replace(/width="800" height="800"/, `width="${VIEW[2]}" height="${PX_H}"`)
      .replace('stop-color="#ff555b"', `stop-color="${s1}"`).replace('stop-color="#bd142b"', `stop-color="${s2}"`)
      .replaceAll('fill="#293449"', `fill="${pants}"`);
    // in-scene use: no motion-accent strokes (they are the root-level <path>s); idle = no waving
    const extra = 'svg > path { display: none; }' + (wave ? '' : ' .wave { animation: none !important; }');
    await page.setContent(`<!doctype html><html><head><style>html,body{margin:0;background:transparent}
      svg{display:block}${extra}</style></head><body>${svg}</body></html>`);
    const n = FPS * LOOP_S;
    for (let f = 0; f < n; f++) {
      await page.evaluate((ms) => document.getAnimations().forEach((a) => { a.pause(); a.currentTime = ms; }), (f * 1000) / FPS);
      await page.screenshot({ path: path.join(tmp, `f_${String(f).padStart(3, '0')}.png`), omitBackground: true });
    }
    const out = path.join(OUT, `${name}.webm`);
    execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-framerate', String(FPS), '-i',
      path.join(tmp, 'f_%03d.png'), '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-b:v', '0', '-crf', '30',
      '-auto-alt-ref', '0', '-row-mt', '1', out]);
    fs.rmSync(tmp, { recursive: true, force: true });
    console.log(`${name}: ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
  }
  await b.close();
})();
