// node thumb.js -> out/VANI_thumbnail.png (1920x1080); assemble a 1280x720 copy with ffmpeg.
const fs = require("fs"), path = require("path"), puppeteer = require("puppeteer-core");
const CHROME = ["C:/Program Files (x86)/Google/Chrome/Application/chrome.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(p => fs.existsSync(p));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: "new" });
  const p = await b.newPage(); await p.setViewport({ width: 1920, height: 1080 });
  await p.goto("file:///" + path.join(__dirname, "stage.html").split(path.sep).join("/"), { waitUntil: "networkidle0" });
  await p.evaluate(async () => { await document.fonts.ready; await document.fonts.load("80px 'Pirata One'"); window.renderScene("thumb", 0); });
  fs.mkdirSync(path.join(__dirname, "out"), { recursive: true });
  await p.screenshot({ path: path.join(__dirname, "out", "VANI_thumbnail.png") });
  await b.close();
})();
