/**
 * Recognizing task-artifact links inside agent messages.
 *
 * The `upload_artifact` tool hands the agent an unsigned object-storage
 * reference derived from its upload URL and asks it to use that in its reply,
 * so artifact references arrive in the transcript as ordinary links. Older
 * replies may still contain the original presigned URL. Rendered as-is they
 * leave the app: the markdown renderer marks anything unrecognized
 * `target="_blank"`, and Electron hands `_blank` to the OS browser. The file
 * never opens in the artifact tab that can display it.
 *
 * The object key carries everything needed to reach that tab. It is built as
 * `<folder>/artifacts/team_<teamId>/task_<taskId>/run_<runId>/<idPrefix>_<name>`
 * (`TaskRun.get_artifact_s3_prefix` plus `products/tasks/backend/facade/api.py`),
 * so task, run, and an 8-character artifact-id prefix are all readable from the
 * path — and readable from links written long before this parser existed. The
 * signature is irrelevant: the app re-presigns through its own API on click, so
 * an expired link still resolves.
 */

const TEAM_SEGMENT_RE = /^team_\d+$/;
const TASK_SEGMENT_RE = /^task_([0-9a-fA-F-]{8,})$/;
const RUN_SEGMENT_RE = /^run_([0-9a-fA-F-]{8,})$/;
const OBJECT_SEGMENT_RE = /^([0-9a-fA-F]{8})_(.+)$/;

export interface ArtifactLinkTarget {
  taskId: string;
  runId: string;
  /** First 8 characters of the artifact id, the only part the key carries. */
  artifactIdPrefix: string;
  /** Storage-safe filename from the key; the display label may differ. */
  fileName: string;
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/**
 * Parse a task-artifact object URL into the ids needed to open it in-app, or
 * null for any other link. Host-agnostic on purpose — the bucket host differs
 * per region and deployment, and matching the key layout is what makes a link
 * an artifact link.
 */
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
  // Walk to the `artifacts` marker rather than indexing from the start: the
  // storage folder prefix is deployment configuration, and path-style S3 URLs
  // carry the bucket as a leading segment.
  for (let index = 0; index + 4 < segments.length; index++) {
    if (segments[index] !== "artifacts") continue;
    if (!TEAM_SEGMENT_RE.test(segments[index + 1])) continue;

    const task = TASK_SEGMENT_RE.exec(segments[index + 2]);
    const run = RUN_SEGMENT_RE.exec(segments[index + 3]);
    const object = OBJECT_SEGMENT_RE.exec(segments[index + 4]);
    if (!task || !run || !object) continue;

    return {
      taskId: task[1],
      runId: run[1],
      artifactIdPrefix: object[1].toLowerCase(),
      fileName: object[2],
    };
  }

  return null;
}

/**
 * Match a parsed link against a run's artifact manifest. `storage_path` is the
 * exact key the URL was built from, so it decides; the id prefix is the
 * fallback for entries stored without a path.
 */
export function findArtifactForLink<
  T extends { id?: string; storage_path?: string },
>(artifacts: readonly T[], target: ArtifactLinkTarget): T | null {
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
