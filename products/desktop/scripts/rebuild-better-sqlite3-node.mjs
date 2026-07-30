// Rebuilds better-sqlite3's native binary for the CURRENT Node ABI.
//
// The Electron app's postinstall rebuilds better-sqlite3 against Electron's
// Node ABI (so the packaged app and `pnpm dev` can open the DB). That same
// binary cannot load under plain Node — vitest then dies with
// "Module did not self-register" / NODE_MODULE_VERSION mismatch. Run this
// before the workspace-server DB tests (CI does this in test.yml) to swap the
// binary back to a Node-ABI build. Re-run `pnpm install` (or the app's
// postinstall) to restore the Electron build before running the app again.
//
// Falls back to compiling with node-gyp when prebuild-install has no binary for
// the running Node (e.g. a release too new to have published prebuilds),
// mirroring rebuild-better-sqlite3-electron.mjs.
import { execFileSync } from "node:child_process";
import { realpathSync, rmSync } from "node:fs";
import { createRequire } from "node:module";

const pkg = realpathSync("node_modules/better-sqlite3");
rmSync(`${pkg}/build`, { recursive: true, force: true });
rmSync(`${pkg}/prebuilds`, { recursive: true, force: true });

const moduleRequire = createRequire(`${pkg}/`);
const run = (args) =>
  execFileSync(process.execPath, args, { cwd: pkg, stdio: "inherit" });

try {
  run([moduleRequire.resolve("prebuild-install/bin.js")]);
} catch (err) {
  console.warn(
    `prebuild-install failed (${err.message}); compiling with node-gyp...`,
  );
  run([
    moduleRequire.resolve("node-gyp/bin/node-gyp.js"),
    "rebuild",
    "--release",
  ]);
}
