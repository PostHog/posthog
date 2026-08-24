import { Lock } from "@phosphor-icons/react";
import { Badge, Button, Text } from "@posthog/quill";
import {
  isImageBuildFailed,
  isImageBuildInProgress,
  type SandboxCustomImage,
  type SandboxCustomImageStatus,
} from "@posthog/shared/domain-types";
import { imageFailureDetail } from "@posthog/ui/features/settings/sections/environments/imageBuildWatcher";

/** The API's status values as words, so no underscore reaches the screen. */
const STATUS_LABELS: Record<SandboxCustomImageStatus, string> = {
  draft: "Draft",
  scanning: "Scanning",
  scan_failed: "Scan failed",
  building: "Building",
  build_failed: "Build failed",
  ready: "Ready",
  archived: "Archived",
};

interface CustomImageListProps {
  images: readonly SandboxCustomImage[];
  /** How many environments start from an image, so archiving is not blind. */
  /** Environments using the image, or null while that count is unknown. */
  usedBy: (imageId: string) => number | null;
  onOpen: (image: SandboxCustomImage) => void;
}

/**
 * The image library. One row per image with a single way in: everything an
 * image needs (its spec, its build log, its name) lives on its own page.
 */
export function CustomImageList({
  images,
  usedBy,
  onOpen,
}: CustomImageListProps) {
  return (
    <div className="flex flex-col divide-y divide-(--gray-4) overflow-hidden rounded-(--radius-3) border border-(--gray-5)">
      {images.map((image) => {
        const used = usedBy(image.id);
        return (
          <div key={image.id} className="flex items-center gap-3 px-3 py-2.5">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex min-w-0 items-center gap-1.5">
                <Text className="truncate font-medium text-(--gray-12) text-[12.5px]">
                  {image.name}
                </Text>
                {image.private && (
                  <Lock
                    size={12}
                    role="img"
                    aria-label="Private, only visible to you"
                    className="shrink-0 text-(--gray-10)"
                  />
                )}
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <StatusBadge image={image} />
                {isImageBuildFailed(image.status) ? (
                  <Text
                    title={imageFailureDetail(image)}
                    className="min-w-0 truncate text-(--red-11) text-[11px]"
                  >
                    {imageFailureDetail(image)}
                  </Text>
                ) : (
                  image.repository && (
                    <Text className="min-w-0 truncate font-mono text-(--gray-10) text-[11px]">
                      {image.repository}
                    </Text>
                  )
                )}
              </div>
            </div>
            <Text className="w-[124px] shrink-0 text-right text-(--gray-10) text-[11px]">
              {used === null
                ? "—"
                : used === 0
                  ? "No environments"
                  : `${used} environment${used === 1 ? "" : "s"}`}
            </Text>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              data-attr="custom-image-open"
              onClick={() => onOpen(image)}
            >
              Open
            </Button>
          </div>
        );
      })}
    </div>
  );
}

/** Status, with the version only once there is a build to point at. */
function StatusBadge({ image }: { image: SandboxCustomImage }) {
  const building = isImageBuildInProgress(image.status);
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <Badge
        variant={
          image.status === "ready"
            ? "success"
            : isImageBuildFailed(image.status)
              ? "destructive"
              : "default"
        }
        className="text-[10.5px]"
      >
        {building && (
          <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-current" />
        )}
        {STATUS_LABELS[image.status]}
      </Badge>
      {image.version > 0 && (
        <Text
          title="Builds auto-increment, including the rebuilds that follow a new sandbox base."
          className="text-(--gray-10) text-[11px] tabular-nums"
        >
          v{image.version}
        </Text>
      )}
    </span>
  );
}
