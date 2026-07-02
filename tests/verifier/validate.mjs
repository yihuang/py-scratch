#!/usr/bin/env node
/**
 * Validate .sb3 files using the official scratch-vm, with asset loading.
 *
 * Reads costume/sound assets from the .sb3 zip so the VM doesn't
 * emit "No storage module present" warnings.  Exits 0 on success.
 *
 * Usage: node validate.mjs <path-to-sb3>
 */

import { readFileSync, existsSync } from "fs";
import VirtualMachine from "scratch-vm";
import pkg from "scratch-storage";
import AdmZip from "adm-zip";

const { ScratchStorage, AssetType, DataFormat } = pkg;

const sb3Path = process.argv[2];

if (!sb3Path || !existsSync(sb3Path)) {
  console.error(`Usage: node validate.mjs <path-to-sb3>`);
  process.exit(1);
}

// ── Read zip and build asset map ───────────────────────────────────
const sb3Data = readFileSync(sb3Path);
const zip = new AdmZip(sb3Data);
const projectJson = JSON.parse(zip.readAsText("project.json"));

const storage = new ScratchStorage();

for (const entry of zip.getEntries()) {
  const name = entry.entryName;
  if (name === "project.json") continue;

  const isVector = name.endsWith(".svg");
  const assetType = isVector ? AssetType.ImageVector : AssetType.ImageBitmap;
  const dataFormat = isVector ? DataFormat.SVG : DataFormat.PNG;

  storage.createAsset(
    assetType,
    DataFormat.PNG,     // dataFormat
    entry.getData(),    // data
    null,               // id (auto-generate)
    true,               // generateId
  );
}

// ── Validate ───────────────────────────────────────────────────────
const vm = new VirtualMachine();
vm.attachStorage(storage);

let success = false;
let errors = [];

try {
  await vm.loadProject(sb3Data);
  success = true;
} catch (e) {
  if (typeof e === "object" && e !== null) {
    const data = e.validationError ? e : JSON.parse(e.message || e);
    errors = data.sb3Errors || [];
    console.error("VALIDATION ERROR:", data.validationError);
  } else {
    errors = [{ message: String(e) }];
  }
}

if (success) {
  console.log("PASS: Project loaded successfully");
  console.log(`Targets: ${vm.runtime.targets.length}`);
  for (const t of vm.runtime.targets) {
    const blockCount = Object.keys(t.blocks._blocks).length;
    console.log(`  ${t.getName()}${t.isStage ? " (stage)" : ""} — ${blockCount} blocks`);
  }
  process.exit(0);
} else {
  console.log(`FAIL: ${errors.length} schema violation(s)`);
  for (const err of errors) {
    console.log(`  - ${err.dataPath}: ${err.message}`);
  }
  process.exit(1);
}
