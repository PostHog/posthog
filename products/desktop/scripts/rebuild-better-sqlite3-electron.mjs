// Rebuilds better-sqlite3's native binary for ELECTRON's Node ABI: downloads
// the official Electron prebuild, falls back to compiling against the Electron
// headers with node-gyp. Counterpart of rebuild-better-sqlite3-node.mjs (see
// "One binary, two ABIs" in docs/TROUBLESHOOTING.md).
//
// This is the only Electron-ABI rebuild postinstall needs: node-pty is N-API
// based and loads under any runtime unchanged. Deliberately avoids
// @electron/rebuild, whose CLI crashes on Node 26+ and whose module walker
// cannot see pnpm's hoisted node_modules.
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const electronVersion = createRequire(`${repoRoot}/apps/code/`)(
  "electron/package.json",
).version;
// Cross-targeted release builds export npm_config_arch (code-release.yml).
// prebuild-install and node-gyp both read it from the environment, but pass it
// explicitly so the contract is visible here.
const arch = process.env.npm_config_arch ?? process.arch;

const moduleDir = path.join(repoRoot, "node_modules/better-sqlite3");
const moduleRequire = createRequire(`${moduleDir}/`);
const prebuildInstall = moduleRequire.resolve("prebuild-install/bin.js");

rmSync(path.join(moduleDir, "build"), { recursive: true, force: true });
rmSync(path.join(moduleDir, "prebuilds"), { recursive: true, force: true });

const run = (args) =>
  execFileSync(process.execPath, args, { cwd: moduleDir, stdio: "inherit" });

console.log(
  `Building better-sqlite3 for Electron ${electronVersion} (${arch})...`,
);
try {
  run([
    prebuildInstall,
    "--runtime=electron",
    `--target=${electronVersion}`,
    `--arch=${arch}`,
  ]);
} catch (err) {
  console.warn(
    `prebuild-install failed (${err.message}); compiling with node-gyp...`,
  );
  // node-gyp is not a dependency of better-sqlite3; it resolves from here only
  // because node-pty depends on it and the hoisted layout puts it at the root.
  run([
    moduleRequire.resolve("node-gyp/bin/node-gyp.js"),
    "rebuild",
    `--target=${electronVersion}`,
    `--arch=${arch}`,
    "--dist-url=https://electronjs.org/headers",
  ]);
}
console.log(`better-sqlite3 built for Electron ${electronVersion}.`);

// pnpm's hoisted layout gives every workspace package that directly depends on
// better-sqlite3 its own physical copy. The rebuild above only touches the root
// copy, but the bundled Electron main process resolves better-sqlite3 from
// apps/code/node_modules first, so a stale binary there fails to load and
// DatabaseService's @postConstruct initializer throws. Mirror the freshly built
// binary into same-version nested copies. The version guard preserves
// workspace-server's Node-ABI binary, which the DB unit tests load directly.
const builtBinary = path.join(moduleDir, "build/Release/better_sqlite3.node");
if (!existsSync(builtBinary)) {
  throw new Error(
    `Expected built binary at ${builtBinary} but none was found.`,
  );
}

const rootVersion = JSON.parse(
  readFileSync(path.join(moduleDir, "package.json"), "utf8"),
).version;

const nestedModuleDirs = ["apps", "packages"].flatMap((group) => {
  const groupDir = path.join(repoRoot, group);
  if (!existsSync(groupDir)) return [];
  return readdirSync(groupDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) =>
      path.join(groupDir, entry.name, "node_modules/better-sqlite3"),
    )
    .filter((dir) => existsSync(path.join(dir, "package.json")));
});

for (const dir of nestedModuleDirs) {
  const relDir = path.relative(repoRoot, dir);
  const version = JSON.parse(
    readFileSync(path.join(dir, "package.json"), "utf8"),
  ).version;
  if (version !== rootVersion) {
    console.log(`Skipping ${relDir} (better-sqlite3 ${version}).`);
    continue;
  }
  const dest = path.join(dir, "build/Release/better_sqlite3.node");
  mkdirSync(path.dirname(dest), { recursive: true });
  copyFileSync(builtBinary, dest);
  console.log(`Synced Electron binary to ${relDir}.`);
}
