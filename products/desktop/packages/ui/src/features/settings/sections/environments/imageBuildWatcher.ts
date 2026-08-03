import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { resolveServiceOptional } from "@posthog/di/container";
import {
  isImageBuildFailed,
  isImageBuildInProgress,
  type SandboxCustomImage,
} from "@posthog/shared/domain-types";
import { NotificationBus } from "@posthog/ui/features/notifications/notifications";

const POLL_INTERVAL_MS = 5000;
const MAX_POLLS = 720;
const MAX_CONSECUTIVE_ERRORS = 3;

const activeWatchers = new Set<string>();

export function imageFailureDetail(image: SandboxCustomImage): string {
  if (image.status === "scan_failed") {
    const highFindings = (image.scan_result?.findings ?? [])
      .filter((finding) => finding.severity === "high")
      .map((finding) => finding.detail);
    if (highFindings.length > 0) return highFindings.join("; ");
  }
  return image.error || "Something went wrong";
}

function notifyBuildResult(image: SandboxCustomImage): void {
  const bus = resolveServiceOptional<NotificationBus>(NotificationBus);
  if (!bus) return;
  const target = image.builder_task_id
    ? ({ kind: "task", taskId: image.builder_task_id } as const)
    : undefined;
  if (image.status === "ready") {
    bus.notify({
      body: `Image "${image.name}" is ready (v${image.version})`,
      target,
      toast: { level: "success" },
    });
    return;
  }
  bus.notify({
    body: `Image "${image.name}" build failed: ${imageFailureDetail(image).split("\n")[0]}`,
    target,
    toast: { level: "error" },
  });
}

export function watchImageBuild(
  client: PostHogAPIClient,
  imageId: string,
  onTerminal?: () => void,
): void {
  if (activeWatchers.has(imageId)) return;
  activeWatchers.add(imageId);

  let polls = 0;
  let consecutiveErrors = 0;

  const timer = setInterval(() => {
    polls += 1;
    client
      .listSandboxCustomImages()
      .then((images) => {
        consecutiveErrors = 0;
        const image = images.find((candidate) => candidate.id === imageId);
        if (!image) {
          stop();
          return;
        }
        if (isImageBuildInProgress(image.status)) {
          if (polls >= MAX_POLLS) stop();
          return;
        }
        stop();
        onTerminal?.();
        if (image.status === "ready" || isImageBuildFailed(image.status)) {
          notifyBuildResult(image);
        }
      })
      .catch(() => {
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS || polls >= MAX_POLLS) {
          stop();
        }
      });
  }, POLL_INTERVAL_MS);

  function stop(): void {
    clearInterval(timer);
    activeWatchers.delete(imageId);
  }
}
