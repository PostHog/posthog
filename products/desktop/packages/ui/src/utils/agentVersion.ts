import semver from "semver";

/** Sentinel version used by unbuilt dev builds (matches the placeholder in
 * `packages/agent/package.json`). Real release builds inject a real semver. */
const DEV_VERSION = "0.0.0-dev";

/**
 * Check whether the connected agent's version satisfies a semver range.
 *
 * Examples:
 *   isAgentVersion(version, ">=0.40.1")
 *   isAgentVersion(version, ">1.0.0")
 *   isAgentVersion(version, ">=0.40.0 <1.0.0")
 *
 * Returns `false` when the agent version is unknown so feature gates fail
 * closed — an unknown agent never accidentally enables a newer code path.
 *
 * The dev sentinel `0.0.0-dev` is treated as "satisfies any range": local
 * dev builds carry the latest code, so we want feature gates to open even
 * though the literal semver is below every released version.
 */
export function isAgentVersion(
  actual: string | undefined,
  range: string,
): boolean {
  if (!actual) return false;
  if (actual === DEV_VERSION) return semver.validRange(range) !== null;
  return semver.satisfies(actual, range, { includePrerelease: true });
}
