import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Desktop links the agent workspace by path, so turbo cannot hash its files. The stamp
// is a turbo global dependency that changes whenever the agent workspace does.
const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const agentWorkspace = resolve(desktopRoot, "../../packages/agent");
const stampFile = join(desktopRoot, ".agent-workspace-stamp");
const SKIPPED = new Set(["node_modules", "dist", ".turbo", "junit.xml"]);

function run(command) {
  execSync(command, { cwd: agentWorkspace, stdio: "inherit" });
}

function sourceFiles(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (SKIPPED.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) sourceFiles(full, out);
    else if (entry.isFile()) out.push(full);
  }
  return out;
}

if (!existsSync(join(agentWorkspace, "node_modules"))) {
  run("pnpm install --frozen-lockfile");
}
run("pnpm build");

const hash = createHash("sha256");
for (const file of sourceFiles(agentWorkspace).sort()) {
  hash.update(relative(agentWorkspace, file).split(sep).join("/"));
  hash.update(readFileSync(file));
}
writeFileSync(stampFile, `${hash.digest("hex")}\n`);
