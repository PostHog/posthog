/**
 * Recognizing task-artifact links inside agent messages.
 *
 * New uploads use an authenticated PostHog download URL containing the task,
 * run, and full artifact id. Existing messages can instead contain a presigned
 * or unsigned object-storage URL. Both forms need to open the artifact tab
 * rather than leave the app, so the parser retains the legacy storage-key path
 * alongside the stable API path.
 */

const ID_SEGMENT_RE = /^[0-9a-fA-F-]{8,}$/;
const TEAM_SEGMENT_RE = /^team_\d+$/;
const TASK_SEGMENT_RE = /^task_([0-9a-fA-F-]{8,})$/;
const RUN_SEGMENT_RE = /^run_([0-9a-fA-F-]{8,})$/;
const OBJECT_SEGMENT_RE = /^([0-9a-fA-F]{8})_(.+)$/;

export type ArtifactLinkTarget =
  | {
      kind: "stable";
      taskId: string;
      runId: string;
      artifactId: string;
    }
  | {
      kind: "legacy-storage";
      taskId: string;
      runId: string;
      /** First 8 characters of the artifact id, the only part the key carries. */
      artifactIdPrefix: string;
      /** Storage-safe filename from the key; the display label may differ. */
      fileName: string;
    };

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Parse a stable API or legacy storage URL into an in-app artifact target. */
export function parseArtifactLink(
  href: string | undefined,
): ArtifactLinkTarget | null {
  if (!href) return null;

  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;

  const segments = url.pathname.split("/").filter(Boolean).map(decodeSegment);
  for (let index = 0; index + 9 < segments.length; index++) {
    if (
      segments[index] !== "api" ||
      segments[index + 1] !== "projects" ||
      segments[index + 3] !== "tasks" ||
      segments[index + 5] !== "runs" ||
      segments[index + 7] !== "artifacts" ||
      segments[index + 9] !== "download" ||
      index + 10 !== segments.length
    ) {
      continue;
    }

    const taskId = segments[index + 4];
    const runId = segments[index + 6];
    const artifactId = segments[index + 8];
    if (
      !ID_SEGMENT_RE.test(taskId) ||
      !ID_SEGMENT_RE.test(runId) ||
      !ID_SEGMENT_RE.test(artifactId)
    ) {
      continue;
    }

    return { kind: "stable", taskId, runId, artifactId };
  }

  // The storage folder prefix varies by deployment, and path-style S3 URLs
  // carry the bucket as a leading segment, so locate the marker dynamically.
  for (let index = 0; index + 4 < segments.length; index++) {
    if (segments[index] !== "artifacts") continue;
    if (!TEAM_SEGMENT_RE.test(segments[index + 1])) continue;

    const task = TASK_SEGMENT_RE.exec(segments[index + 2]);
    const run = RUN_SEGMENT_RE.exec(segments[index + 3]);
    const object = OBJECT_SEGMENT_RE.exec(segments[index + 4]);
    if (!task || !run || !object) continue;

    return {
      kind: "legacy-storage",
      taskId: task[1],
      runId: run[1],
      artifactIdPrefix: object[1].toLowerCase(),
      fileName: object[2],
    };
  }

  return null;
}

/** Match stable links by full id and legacy links by storage key or id prefix. */
export function findArtifactForLink<
  T extends { id?: string; storage_path?: string },
>(artifacts: readonly T[], target: ArtifactLinkTarget): T | null {
  if (target.kind === "stable") {
    return (
      artifacts.find(
        (artifact) =>
          artifact.id?.toLowerCase() === target.artifactId.toLowerCase(),
      ) ?? null
    );
  }

  const keySuffix = `/${target.artifactIdPrefix}_${target.fileName}`;
  const byPath = artifacts.find((artifact) =>
    artifact.storage_path?.endsWith(keySuffix),
  );
  if (byPath) return byPath;

  const matchingIds = artifacts.filter((artifact) =>
    artifact.id?.toLowerCase().startsWith(target.artifactIdPrefix),
  );
  // An 8-character prefix is not a guarantee of uniqueness. Two matches mean we
  // cannot tell which file the link meant, and opening the wrong one is worse
  // than leaving the link alone.
  return matchingIds.length === 1 ? matchingIds[0] : null;
}
