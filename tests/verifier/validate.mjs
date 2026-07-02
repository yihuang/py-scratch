#!/usr/bin/env node
/**
 * Validate .sb3 files using the official scratch-vm.
 * Usage: node validate.mjs [path-to-sb3]
 * Default: /tmp/validate.sb3
 */

import { readFileSync, existsSync } from "fs";
import VirtualMachine from "scratch-vm";

const sb3Path = process.argv[2] || "/tmp/validate.sb3";

if (!existsSync(sb3Path)) {
  console.error(`File not found: ${sb3Path}`);
  process.exit(1);
}

const vm = new VirtualMachine();
const sb3Data = readFileSync(sb3Path);

let success = false;
let errors = [];

vm.runtime.targets = [];

try {
  await vm.loadProject(sb3Data);
  success = true;
} catch (e) {
  // Catch structured error from scratch-vm
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
