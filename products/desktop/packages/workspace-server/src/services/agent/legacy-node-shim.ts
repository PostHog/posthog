import { existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const LEGACY_SHIM_DIR_NAMES = ["agent-node-dev", "agent-node-prod"];

export interface LegacyNodeShimCleanup {
  removed: string[];
  failed: string[];
}

// Releases before the shim removal published a `node` alias for the app binary
// in these dirs and put them on agent PATHs. Stale copies keep phantom-booting
// the desktop app from process trees that outlive an update, so delete them at
// every boot. Remove once no supported release writes the shim.
export function removeLegacyNodeShimDirs(
  tmpRoot: string = tmpdir(),
): LegacyNodeShimCleanup {
  const removed: string[] = [];
  const failed: string[] = [];
  for (const name of LEGACY_SHIM_DIR_NAMES) {
    const dir = join(tmpRoot, name);
    if (!existsSync(dir)) continue;
    try {
      rmSync(dir, { recursive: true, force: true });
      removed.push(dir);
    } catch {
      failed.push(dir);
    }
  }
  return { removed, failed };
}
