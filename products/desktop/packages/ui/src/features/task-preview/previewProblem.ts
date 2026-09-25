import type { TaskRunPreviewSession } from "@posthog/shared/domain-types";

export type PreviewProblem =
  | "not_ready"
  | "ended"
  | "unavailable"
  | "load_failed"
  | "error";

export function previewProblem({
  session,
  isError,
  loadFailed,
}: {
  session: TaskRunPreviewSession | undefined;
  isError: boolean;
  loadFailed: boolean;
}): PreviewProblem | null {
  if (isError) return "error";
  if (!session) return null;
  if (session.outcome !== "ready") return session.outcome;
  if (!session.url) return "unavailable";
  return loadFailed ? "load_failed" : null;
}
