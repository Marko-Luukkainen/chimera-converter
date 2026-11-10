/**
 * Headless-Chromium test of the anatomy switch (Classic / MRI in the top bar): the voice is rebuilt
 * with the MRI contour anatomy, the views follow its telemetry, the choice survives a body change
 * and the body pad, it speaks and sings, the 3D view draws it, and nothing logs an error.
 * Usage: bun tools/e2e-anatomy.ts [url] [outdir]   (against `bun run preview`)
 */
import { chromium, type Page } from "playwright-core";
import { mkdirSync } from "node:fs";

const url = process.argv[2] ?? "http://127.0.0.1:5318/";
const outDir = process.argv[3] ?? "out/e2e-anatomy";
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true, args: ["--autoplay-policy=no-user-gesture-required", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const errors: string[] = [];
const fail = (m: string) => errors.push(m);

const latest = (page: Page) =>
  page.evaluate(() => {
    // @ts-expect-error debug handle
    const e = window.__chimeraEngine;
    const t = e?.latest;
    return t ? { body: t.body, rms: t.t?.outRms ?? -1, nPh: t.nPh, nOr: t.nOr } : null;
  });
const checked = (page: Page, name: string) => page.getByRole("radio", { name, exact: true }).getAttribute("aria-checked");
/** pixels of the 2D face canvas, to tell two drawings apart */
const faceHash = (page: Page) =>
  page.evaluate(() => {
    const c = document.querySelector(".anatomy canvas") as HTMLCanvasElement | null;
    if (!c) return "";
    const d = c.toDataURL();
    let h = 0;
    for (let i = 0; i < d.length; i += 7) h = (h * 31 + d.charCodeAt(i)) | 0;
    return `${c.width}x${c.height}:${h}`;
  });

const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
page.on("console", (m) => m.type() === "error" && fail(`console: ${m.text()}`));
page.on("pageerror", (e) => fail(`pageerror: ${e.message}`));
await page.goto(url, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /breathe in and start/i }).click();
await page.waitForTimeout(1500);

// 1. the switch is there and starts on Classic
if ((await checked(page, "Classic")) !== "true") fail("Classic is not selected at start");
if ((await checked(page, "MRI")) !== "false") fail("MRI is selected at start");
await page.locator(".topbar").screenshot({ path: `${outDir}/1-topbar.png` });
await page.keyboard.down("d");
await page.waitForTimeout(700);
const classicFace = await faceHash(page);
const classic = await latest(page);
await page.screenshot({ path: `${outDir}/2-classic.png` });
await page.keyboard.up("d");

// 2. MRI: the voice is rebuilt with the contour anatomy, and the views take its telemetry
await page.getByRole("radio", { name: "MRI", exact: true }).click();
await page.waitForTimeout(1200);
if ((await checked(page, "MRI")) !== "true") fail("MRI did not select");
await page.keyboard.down("d");
await page.waitForTimeout(900);
const mri = await latest(page);
const mriFace = await faceHash(page);
await page.screenshot({ path: `${outDir}/3-mri.png` });
await page.keyboard.up("d");
console.log(`telemetry body classic ${JSON.stringify(classic?.body)} rms ${classic?.rms.toFixed(4)}; MRI ${JSON.stringify(mri?.body)} rms ${mri?.rms.toFixed(4)}`);
if (mri?.body?.model !== "contour") fail(`telemetry body after MRI: ${JSON.stringify(mri?.body)} (the views ignore telemetry of another body)`);
if (!(mri && mri.rms > 0.01)) fail(`no sound with the MRI anatomy (rms ${mri?.rms})`);
if (classicFace === mriFace) fail("the face drawing did not change with the anatomy");
const live = await page.evaluate(() => {
  // the views draw live telemetry only when it is the store's body
  // @ts-expect-error debug handle
  const e = window.__chimeraEngine;
  return e?.latest ? JSON.stringify(e.latest.body) : null;
});
console.log(`latest telemetry body: ${live}`);

// 3. the choice survives a preset and the body pad
await page.getByRole("radio", { name: "Female", exact: true }).click();
await page.waitForTimeout(1200);
if ((await checked(page, "MRI")) !== "true") fail("MRI lost on switching to Female");
const fem = await latest(page);
if (fem?.body?.model !== "contour" || fem?.body?.female !== 1) fail(`female body after the preset: ${JSON.stringify(fem?.body)}`);
const pad = await page.locator(".body-pad").boundingBox();
if (pad) {
  await page.mouse.move(pad.x + pad.width * 0.5, pad.y + pad.height * 0.3);
  await page.mouse.down();
  await page.mouse.move(pad.x + pad.width * 0.4, pad.y + pad.height * 0.45, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(1200);
  const mix = await latest(page);
  console.log(`after the body pad: ${JSON.stringify(mix?.body)}`);
  if (mix?.body?.model !== "contour") fail(`MRI lost on the body pad: ${JSON.stringify(mix?.body)}`);
  if ((await checked(page, "MRI")) !== "true") fail("MRI radio unchecked after the body pad");
}
await page.getByRole("radio", { name: "Male", exact: true }).click();
await page.waitForTimeout(1200);

// 4. speech with the MRI anatomy: sound, then silence
await page.getByRole("radio", { name: "Speak" }).click();
await page.waitForTimeout(300);
await page.getByRole("button", { name: /^Speak$/ }).click();
const rms: number[] = [];
for (let i = 0; i < 14; i++) {
  await page.waitForTimeout(220);
  if (i === 3) await page.screenshot({ path: `${outDir}/4-speak-mri.png` });
  rms.push((await latest(page))?.rms ?? -1);
}
console.log(`speech rms ${rms.map((r) => r.toFixed(3)).join(",")}`);
if (!(Math.max(...rms) > 0.01)) fail(`MRI speech silent: ${rms.join(",")}`);
if (!(Math.max(...rms.slice(-2)) < 1e-3)) fail(`MRI voice still sounding after the phrase: ${rms.slice(-2).join(",")}`);

// 5. the 3D view with the MRI anatomy
await page.getByRole("radio", { name: "Play" }).click();
await page.waitForTimeout(300);
await page.getByRole("switch", { name: "3D" }).or(page.getByRole("checkbox", { name: "3D" })).or(page.getByLabel("3D")).first().click();
await page.waitForTimeout(2500);
await page.keyboard.down("d");
await page.waitForTimeout(900);
await page.screenshot({ path: `${outDir}/5-mri-3d.png` });
await page.keyboard.up("d");

// 6. back to Classic
await page.getByRole("radio", { name: "Classic", exact: true }).click();
await page.waitForTimeout(1200);
const back = await latest(page);
if (back?.body?.model) fail(`telemetry still MRI after Classic: ${JSON.stringify(back?.body)}`);
if ((await checked(page, "Classic")) !== "true") fail("Classic did not select again");

await browser.close();
console.log(errors.length ? `FAILED:\n  ${errors.join("\n  ")}` : "anatomy switch: all checks passed");
process.exit(errors.length ? 1 : 0);
