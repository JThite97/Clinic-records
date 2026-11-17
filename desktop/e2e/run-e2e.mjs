// End-to-end test: starts the real server (with the built UI) on a temporary
// data folder and drives the main doctor workflow in Chromium.
//   npm run build && npm run e2e
// Needs the backend virtualenv at ../backend/.venv (or PYTHON=...).
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const py = process.env.PYTHON || join(root, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const port = 8765;
const home = mkdtempSync(join(tmpdir(), "clinic-e2e-"));
const shots = join(here, "screenshots");
mkdirSync(shots, { recursive: true });

const server = spawn(py, ["-m", "clinic", "--home", home, "--port", String(port)], {
  cwd: join(root, "backend"), env: { ...process.env, CLINIC_UI_DIR: join(root, "desktop", "dist") }, stdio: ["ignore", "pipe", "pipe"],
});
let serverLog = "";
server.stdout.on("data", (d) => (serverLog += d));
server.stderr.on("data", (d) => (serverLog += d));

const base = `http://127.0.0.1:${port}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitUp() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(base + "/api/health"); if (r.ok) return; } catch { /* retry */ }
    await sleep(250);
  }
  throw new Error("server did not start\n" + serverLog);
}

let failures = 0;
async function step(name, fn) {
  try { await fn(); console.log("  ✓", name); }
  catch (e) { failures++; console.log("  ✗", name, "\n   ", e.message.split("\n")[0]); }
}
function expect(cond, msg) { if (!cond) throw new Error(msg); }

const browser = await chromium.launch();
try {
  await waitUp();
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
  page.setDefaultTimeout(8000);
  page.on("pageerror", (e) => { failures++; console.log("  page error:", e.message); });
  const shot = (n) => page.screenshot({ path: join(shots, `${n}.png`) });
  await page.goto(base + "/");

  await step("first-run setup creates the clinic", async () => {
    await page.getByLabel("Clinic name").fill("Sunrise Clinic");
    await page.getByLabel("Doctor's name").fill("Dr. Asha Rao");
    await page.getByLabel("Username").fill("asha");
    await page.getByLabel("Password", { exact: true }).fill("correct-horse-1");
    await page.getByLabel("Confirm password").fill("correct-horse-1");
    await shot("01-setup");
    await page.getByRole("button", { name: "Create clinic" }).click();
    await page.getByRole("heading", { name: "Today", exact: true }).waitFor();
    await shot("02-dashboard-empty");
  });

  await step("register a patient (P000001)", async () => {
    await page.getByRole("link", { name: "New patient" }).first().click();
    await page.getByLabel("Full name").fill("Ravi Kumar");
    await page.getByLabel("Sex").selectOption("M");
    await page.getByLabel("Age (years)").fill("42");
    await page.getByLabel("Phone", { exact: true }).fill("9876543210");
    await page.getByLabel("Allergies").fill("Penicillin");
    await page.getByRole("button", { name: "Save patient" }).click();
    await page.getByText("Allergies: Penicillin").waitFor();
    expect(await page.locator(".patient-head").getByText("P000001").isVisible(), "patient number missing");
  });

  await step("record a visit with vitals and a typeahead prescription", async () => {
    await page.getByRole("button", { name: "New visit" }).click();
    await page.getByLabel("Systolic").fill("130");
    await page.getByLabel("Diastolic").fill("85");
    await page.getByLabel("Temp °C").fill("38.4");
    await page.getByLabel("Chief complaints").fill("Fever and body ache for 2 days");
    await page.getByLabel("Diagnosis").fill("Viral fever");
    const add = page.getByLabel("Add medicine");
    await add.fill("paracetamol 650");
    await page.getByRole("option", { name: /Paracetamol 650 mg/ }).click();
    await add.fill("cetiriz");
    await page.getByRole("option").first().waitFor();
    await add.press("Enter");
    await add.fill("ORS home made");
    await page.getByText("Add “ORS home made” as written").click();
    expect((await page.getByLabel("Medicine name").count()) === 3, "expected 3 medicines");
    expect((await page.getByLabel("Quantity").first().inputValue()) === "9", "quantity suggestion for 1-1-1 x 3 days");
    await page.getByRole("button", { name: "+7d" }).click();
    await shot("03-visit-workspace");
    await page.getByRole("button", { name: /^Save/ }).first().click();
    await page.getByRole("heading", { name: /^Visit ·/ }).waitFor();
    await shot("04-visit-view");
  });

  await step("prescription PDF opens", async () => {
    const [req] = await Promise.all([
      page.context().waitForEvent("request", { predicate: (r) => r.url().includes("prescription.pdf") }),
      page.getByRole("button", { name: "Print prescription" }).click(),
    ]);
    const url = req.url();
    const r = await fetch(url);
    expect(r.headers.get("content-type") === "application/pdf", "not a PDF");
    for (const p of page.context().pages()) if (p !== page) await p.close();
  });

  await step("second visit shows the previous visit and copies its prescription", async () => {
    await page.getByRole("link", { name: /Ravi Kumar/ }).click();
    await page.getByRole("button", { name: "New visit" }).click();
    await page.getByText("Previous visit").waitFor();
    expect(await page.locator(".history-pane").getByText("Viral fever").isVisible(), "previous diagnosis not shown");
    await page.getByRole("button", { name: /^Copy from/ }).click();
    expect((await page.getByLabel("Medicine name").count()) === 3, "copy-previous did not load 3 medicines");
    await page.getByLabel("Diagnosis").fill("Recovering");
    await shot("05-second-visit-copy");
    await page.keyboard.press("Control+s");
    await page.getByRole("heading", { name: /^Visit ·/ }).waitFor();
  });

  await step("amend the first (locked) visit: reason required, original kept", async () => {
    await page.getByRole("link", { name: /Ravi Kumar/ }).click();
    await page.locator(".visit-card", { hasText: "Viral fever" }).click();
    await page.getByRole("link", { name: "Amend" }).click();
    await page.getByLabel("Diagnosis").fill("Dengue fever (NS1 positive)");
    await page.getByRole("button", { name: /^Save/ }).first().click();
    await page.getByText("A reason is required").waitFor();
    await page.getByLabel(/Reason for amendment/).fill("NS1 report received");
    await page.getByRole("button", { name: /^Save/ }).first().click();
    await page.getByText("Version history").waitFor();
    expect(await page.getByRole("cell", { name: "Viral fever" }).isVisible(), "original version missing from history");
    await shot("06-amended-history");
  });

  await step("upload a lab report to the document vault", async () => {
    await page.getByRole("link", { name: /Ravi Kumar/ }).click();
    await page.getByRole("button", { name: /^Documents/ }).click();
    const f = join(home, "cbc.pdf");
    writeFileSync(f, "%PDF-1.4\n% fake CBC report\n");
    await page.locator('input[type="file"]').setInputFiles(f);
    await page.getByLabel("Title").fill("CBC 17 Nov");
    await page.getByRole("button", { name: "Add document" }).click();
    await page.getByText("CBC 17 Nov").waitFor();
    await page.getByRole("button", { name: "Verify" }).click();
    await page.getByText("Checksum OK").waitFor();
    await shot("07-documents");
  });

  await step("search finds the patient by typo, ID and phone", async () => {
    await page.getByRole("link", { name: "Patients", exact: true }).click();
    for (const q of ["Ravi Kumr", "P000001", "43210"]) {
      await page.getByLabel("Search patients").fill(q);
      await page.locator("tbody tr", { hasText: "Ravi Kumar" }).waitFor();
    }
    await shot("08-patients");
  });

  await step("back up now and verify", async () => {
    await page.getByRole("link", { name: "Backups" }).click();
    await page.getByRole("button", { name: "Back up now" }).click();
    await page.getByText("Backup created and verified").waitFor();
    await page.getByRole("button", { name: "Verify" }).first().click();
    await page.getByText("every file checked OK").waitFor();
    await shot("09-backups");
  });

  await step("settings: letterhead details save", async () => {
    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByLabel("Qualifications").fill("MBBS, MD (Medicine)");
    await page.getByLabel("Registration number").fill("MMC 12345");
    await page.getByRole("button", { name: "Save clinic details" }).click();
    await page.getByText("Clinic details saved").waitFor();
    await shot("10-settings");
  });

  await step("audit log is intact", async () => {
    await page.getByRole("link", { name: "Audit log" }).click();
    await page.getByText("Integrity check passed").waitFor();
  });

  await step("dashboard lists today's visits and follow-up", async () => {
    await page.getByRole("link", { name: "Today" }).click();
    await page.locator(".list").first().getByText("Ravi Kumar").first().waitFor();
    await shot("11-dashboard");
  });

  await step("lock closes the database; login reopens it", async () => {
    await page.getByRole("button", { name: "Lock" }).click();
    await page.getByRole("button", { name: "Log in" }).waitFor();
    const s = await (await fetch(base + "/api/system/status")).json();
    expect(s.unlocked === false, "database still unlocked");
    await page.getByLabel("Username").fill("asha");
    await page.getByLabel("Password").fill("correct-horse-1");
    await page.getByRole("button", { name: "Log in" }).click();
    await page.getByRole("heading", { name: "Today", exact: true }).waitFor();
  });

  await step("mobile read-only page works", async () => {
    const m = await browser.newPage({ viewport: { width: 390, height: 800 } });
    await m.goto(base + "/mobile");
    await m.getByLabel("Username").fill("asha");
    await m.getByLabel("Password").fill("correct-horse-1");
    await m.getByRole("button", { name: "Log in" }).click();
    await m.getByText("Ravi Kumar").first().click();
    await m.getByText("Dengue fever (NS1 positive)").waitFor();
    await m.screenshot({ path: join(shots, "12-mobile.png") });
    await m.close();
  });
} finally {
  await browser.close();
  server.kill();
  rmSync(home, { recursive: true, force: true });
}
console.log(failures ? `\n${failures} step(s) failed` : "\nAll end-to-end steps passed");
if (failures) { console.log(serverLog.split("\n").filter((l) => /ERROR|Traceback/.test(l)).slice(-20).join("\n")); }
process.exit(failures ? 1 : 0);
