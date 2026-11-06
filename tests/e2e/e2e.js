// End-to-end check of ComfyUI-freefield in a real ComfyUI: the tab, the catalog, opening apps, a run, a download.
//
//   python tests/e2e/fake_hf.py 8799 &                     # a stand-in for Hugging Face (3 MB per file)
//   cd ComfyUI && FREEFIELD_DEV=1 FREEFIELD_EXAMPLES_DIR=/path/to/freefield HF_ENDPOINT=http://127.0.0.1:8799 \
//       python main.py --cpu --port 8190 &                  # with this repo in custom_nodes/
//   node tests/e2e/e2e.js http://127.0.0.1:8190/ shots/     # needs playwright; prints what it saw as JSON
//
// FREEFIELD_DEV=1 lists the model-free smoke app it runs. The downloads expect these files to be missing: Smooth's model;
// for Styles, its diffusion model (from every diffusion_models folder), the example's LoRA and the other styles' LoRAs.
const { chromium } = require("playwright");
const BASE = process.argv[2], SHOTS = process.argv[3];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1500, height: 940 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push("pageerror: " + e.message));
  p.on("console", (m) => { if (m.type() === "error" && /freefield|ff-/i.test(m.text())) errs.push("console: " + m.text()); });
  const out = {};
  await p.goto(BASE, { waitUntil: "networkidle" });
  await p.waitForFunction(() => window.app && window.app.graph, null, { timeout: 60000 });
  await sleep(2500);
  for (let i = 0; i < 3; i++) { await p.keyboard.press("Escape"); await sleep(300); }
  out.catalog = await p.evaluate(async () => { const r = await fetch("/api/freefield/catalog"); const d = await r.json(); return { status: r.status, apps: d.apps.length, cats: d.categories.length, ready: d.apps.filter((a) => a.status.ready).map((a) => a.id) }; });
  // the tab
  const btn = p.locator("i.pi-th-large").first();
  out.tabButton = await btn.count();
  await btn.click();
  await p.waitForSelector(".ff-card", { timeout: 15000 });
  out.cards = await p.locator(".ff-card").count();
  // the 24 GB label: apps that ran on an RTX 3090 Ti through the node say so; the others keep Freefield's estimate
  out.vramBadges = await p.evaluate(() => Object.fromEntries(["dub", "cinema-video", "extend-video", "music"].map((id) =>
    [id, [...document.querySelectorAll(`.ff-card[data-open="${id}"] .ff-badge`)].map((b) => b.textContent.trim())])));
  await p.screenshot({ path: `${SHOTS}/1-list.png` });
  // search, then an app's page
  await p.fill(".ff-search", "face swap");
  await sleep(300);
  out.cardsAfterSearch = await p.locator(".ff-card").count();
  await p.locator('.ff-card[data-open="face-swap"]').click();
  await p.waitForSelector(".ff-detail");
  await p.screenshot({ path: `${SHOTS}/2-detail.png` });
  // open with the example: a new workflow tab with the app's nodes and the example's files in the loaders
  await p.locator('[data-act="example"]').click();
  await sleep(3500);
  out.faceSwap = await p.evaluate(() => {
    const nodes = app.graph._nodes || app.graph.nodes || [];
    const loads = nodes.filter((n) => n.type === "LoadImage").map((n) => n.widgets?.find((w) => w.name === "image")?.value);
    return { nodes: nodes.length, loadImages: loads };
  });
  out.faceSwapApi = await p.evaluate(async () => { const r = await fetch("/api/freefield/open", { method: "POST", body: JSON.stringify({ id: "face-swap", example: true }) }); const d = await r.json(); return Object.keys(d.prompt).length; });
  out.tabs = await p.evaluate(() => [...document.querySelectorAll(".workflow-tabs .workflow-label, .p-togglebutton-label, [class*='workflow-tab'] span")].map((e) => e.textContent.trim()).filter(Boolean));
  out.openWorkflows = await p.evaluate(() => (app.extensionManager?.workflow?.openWorkflows || []).map((w) => w.filename || w.path));
  await p.screenshot({ path: `${SHOTS}/3-loaded.png` });
  // a model-free app all the way through ComfyUI's queue
  await p.locator("[data-back]").click();
  await p.fill(".ff-search", "smoke");
  await sleep(300);
  await p.locator('.ff-card[data-open="smoke"]').click();
  await p.locator('[data-act="empty"]').click();
  await sleep(2500);
  const before = await p.evaluate(async () => Object.keys(await (await fetch("/api/history")).json()).length);
  await p.evaluate(async () => { await app.queuePrompt(0, 1); });
  let hist = null;
  for (let i = 0; i < 40 && !hist; i++) {
    await sleep(500);
    hist = await p.evaluate(async (n) => { const h = await (await fetch("/api/history")).json(); const ks = Object.keys(h); if (ks.length <= n) return null; const e = h[ks[ks.length - 1]]; return { status: e.status?.status_str, outputs: Object.keys(e.outputs || {}).length }; }, before);
  }
  out.smokeRun = hist;
  // a download: the fake Hugging Face serves 3 MB per file
  await p.locator("[data-back]").click();
  await p.fill(".ff-search", "smooth");
  await sleep(300);
  await p.locator('.ff-card[data-open="smooth"]').click();
  out.smoothBefore = await p.locator(".ff-detail .ff-models .ff-missing").count();
  await p.locator('[data-act="download"]').click();
  for (let i = 0; i < 40; i++) { await sleep(500); if (await p.locator(".ff-detail .ff-models .ff-missing").count() === 0) break; }
  out.smoothAfter = await p.locator(".ff-detail .ff-models .ff-missing").count();
  out.smoothJob = await p.evaluate(async () => (await (await fetch("/api/freefield/downloads")).json())["smooth"]);
  await p.screenshot({ path: `${SHOTS}/4-downloaded.png` });
  // Styles: Download gets what the workflow loads (its model and the example's LoRA), "Download these too" the other styles
  const blocks = () => p.evaluate(() => [...document.querySelectorAll(".ff-detail .ff-block")].filter((b) => b.querySelector(".ff-models"))
    .map((b) => ({ title: b.querySelector("h4").firstChild.textContent.trim(), rows: b.querySelectorAll("li").length,
                   missing: b.querySelectorAll(".ff-missing").length, button: b.querySelector(".ff-btn")?.textContent.trim() || null })));
  await p.locator("[data-back]").click();
  await p.fill(".ff-search", "styles");
  await sleep(300);
  await p.locator('.ff-card[data-open="styles"]').click();
  out.stylesBefore = await blocks();
  out.stylesVram = await p.locator(".ff-vram").textContent();
  await p.screenshot({ path: `${SHOTS}/5-styles.png` });
  await p.locator('[data-act="download"]').click();
  for (let i = 0; i < 40; i++) { await sleep(500); if ((await blocks())[0].missing === 0) break; }
  out.stylesAfterDownload = await blocks();
  await p.locator('[data-act="download-extra"]').click();
  for (let i = 0; i < 60; i++) { await sleep(500); const b = await blocks(); if (b[1] && b[1].missing === 0) break; }
  out.stylesAfterExtra = await blocks();
  out.stylesJob = await p.evaluate(async () => (await (await fetch("/api/freefield/downloads")).json())["styles"]);
  out.errors = errs;
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})().catch((e) => { console.error("E2E FAILED", e); process.exit(1); });
