// Render stage.html to frames with headless Chrome.
//   node render.js frames            -> frames/000000.jpg ... at 25 fps for the whole timeline
//   node render.js stills            -> stills/<scene>.jpg, one frame from the middle of each scene
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const CHROME = ["C:/Program Files (x86)/Google/Chrome/Application/chrome.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(p => fs.existsSync(p));
const FPS = 25;
const mode = process.argv[2] || "stills";
const timeline = JSON.parse(fs.readFileSync(path.join(__dirname, "timeline.json"), "utf8"));

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--hide-scrollbars"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  await page.goto("file:///" + path.join(__dirname, "stage.html").replace(/\\/g, "/"), { waitUntil: "networkidle0" });
  await page.evaluate(tl => { window.TIMELINE = tl; }, timeline);
  await page.evaluate(async () => { await document.fonts.ready; await document.fonts.load("80px 'Pirata One'"); });
  const shot = async (t, file) => { await page.evaluate(x => window.renderAt(x), t); await page.screenshot({ path: file, type: "jpeg", quality: 92 }); };
  if (mode === "stills") {
    fs.mkdirSync(path.join(__dirname, "stills"), { recursive: true });
    for (const s of timeline) await shot(s.start + s.dur * 0.75, path.join(__dirname, "stills", `${s.id}.jpg`));
  } else {
    const dir = path.join(__dirname, "frames");
    fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir);
    const end = timeline[timeline.length - 1].start + timeline[timeline.length - 1].dur;
    const n = Math.ceil(end * FPS);
    for (let i = 0; i < n; i++) {
      await shot(i / FPS, path.join(dir, String(i).padStart(6, "0") + ".jpg"));
      if (i % 250 === 0) console.log(`frame ${i}/${n}`);
    }
  }
  await browser.close();
})();
