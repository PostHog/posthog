import { Cube } from "@phosphor-icons/react";
import type { Task } from "@posthog/shared/domain-types";
import { Badge } from "../../../primitives/Badge";
import { Tooltip } from "../../../primitives/Tooltip";
import { openSettings } from "../../settings/hooks/useOpenSettings";
import { useSandboxCustomImages } from "../../settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "../../settings/sections/environments/useSandboxEnvironments";

export function CustomImageBadge({ task }: { task: Task }) {
  const run = task.latest_run;
  const state = run?.state as
    | { custom_image_id?: unknown; sandbox_environment_id?: unknown }
    | undefined;
  const customImageId =
    typeof state?.custom_image_id === "string" ? state.custom_image_id : null;
  const sandboxEnvironmentId =
    typeof state?.sandbox_environment_id === "string"
      ? state.sandbox_environment_id
      : null;

  // Only mount the data-fetching part when the run could have used a custom image.
  if (
    run?.environment !== "cloud" ||
    (!customImageId && !sandboxEnvironmentId)
  ) {
    return null;
  }
  return (
    <ResolvedCustomImageBadge
      customImageId={customImageId}
      sandboxEnvironmentId={sandboxEnvironmentId}
    />
  );
}

function ResolvedCustomImageBadge({
  customImageId,
  sandboxEnvironmentId,
}: {
  customImageId: string | null;
  sandboxEnvironmentId: string | null;
}) {
  const { images } = useSandboxCustomImages();
  const { environments } = useSandboxEnvironments();

  const environment = sandboxEnvironmentId
    ? environments.find((env) => env.id === sandboxEnvironmentId)
    : undefined;
  const imageId = customImageId ?? environment?.custom_image_id ?? null;
  if (!imageId) return null;

  const imageName =
    images.find((image) => image.id === imageId)?.name ??
    environment?.custom_image_name ??
    null;

  return (
    <Tooltip
      content={`Runs on custom base image${imageName ? ` "${imageName}"` : ""}. Click to manage custom images.`}
      side="bottom"
      delayDuration={300}
    >
      <button
        type="button"
        className="no-drag flex shrink-0 cursor-pointer items-center"
        aria-label="Manage custom images"
        onClick={() => openSettings("cloud-environments")}
      >
        <Badge color="violet" className="flex items-center gap-1">
          <Cube size={10} weight="fill" />
          {imageName ? `Custom VM · ${imageName}` : "Custom VM"}
        </Badge>
      </button>
    </Tooltip>
  );
}
