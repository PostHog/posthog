import { X } from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { ReleaseNotesSections } from "@posthog/ui/features/updates/ReleaseNotesSections";
import { parseReleaseNotes } from "@posthog/ui/features/updates/releaseNotes";
import { useUpdateModalStore } from "@posthog/ui/features/updates/updateModalStore";
import {
  useHasActiveUpdate,
  useInstallUpdate,
  useUpdateView,
} from "@posthog/ui/features/updates/updateStore";
import {
  Button,
  Dialog,
  Flex,
  IconButton,
  Progress,
  ScrollArea,
  Skeleton,
  Text,
} from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";

function formatSpeed(bytesPerSecond: number | null): string {
  if (!bytesPerSecond || bytesPerSecond <= 0) return "";
  return `${(bytesPerSecond / (1024 * 1024)).toFixed(1)} MB/s`;
}

function formatSize(bytes: number | null): string {
  if (!bytes || bytes <= 0) return "";
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

function ReleaseNotesSkeleton() {
  return (
    <Flex direction="column" gap="3">
      {["improved", "fixed"].map((key) => (
        <Flex key={key} direction="column" gap="2">
          <Skeleton width="56px" height="12px" />
          <Skeleton width="90%" height="14px" />
          <Skeleton width="80%" height="14px" />
        </Flex>
      ))}
    </Flex>
  );
}

export function UpdateAvailableModal() {
  const isOpen = useUpdateModalStore((state) => state.isOpen);
  const close = useUpdateModalStore((state) => state.close);
  const {
    status,
    version,
    availableVersion,
    releaseNotes,
    downloadPercent,
    bytesPerSecond,
    downloadSizeBytes,
  } = useUpdateView();
  const installUpdate = useInstallUpdate();
  const hostTRPC = useHostTRPC();
  const downloadMutation = useMutation(
    hostTRPC.updates.download.mutationOptions(),
  );
  const prefetchForActiveUpdate = useHasActiveUpdate();
  const targetVersion = version ?? availableVersion;
  const { data: releasesData, isPending: isPendingReleases } = useQuery({
    ...hostTRPC.releaseFeed.list.queryOptions(
      targetVersion ? { expectVersion: targetVersion } : undefined,
    ),
    enabled: isOpen || prefetchForActiveUpdate,
  });

  const percent = Math.round(downloadPercent ?? 0);
  const sizeLabel = formatSize(downloadSizeBytes);
  const isDownloading = status === "downloading";
  const isReady = status === "ready" || status === "installing";

  const releases = releasesData?.releases ?? [];
  const latestRelease = releases.find((r) => !r.isPrerelease) ?? releases[0];
  const noteRelease =
    releases.find((r) => r.version === targetVersion) ?? latestRelease;
  const rawNotes = noteRelease?.notes?.trim()
    ? noteRelease.notes
    : releaseNotes;
  const parsedNotes = rawNotes ? parseReleaseNotes(rawNotes) : null;
  const hasParsedNotes =
    !!parsedNotes &&
    (parsedNotes.improved.length > 0 || parsedNotes.fixed.length > 0);

  return (
    <Dialog.Root
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Dialog.Content maxWidth="440px">
        <Flex direction="column" gap="4">
          <Flex justify="between" align="start" gap="3">
            <Flex direction="column" gap="1">
              <Dialog.Title className="mb-0">
                {isReady ? "Update ready" : "Update available"}
              </Dialog.Title>
              <Dialog.Description>
                <Text color="gray" size="2">
                  {targetVersion
                    ? `PostHog ${targetVersion}${sizeLabel ? ` · ${sizeLabel}` : ""}`
                    : "A new version is available"}
                </Text>
              </Dialog.Description>
            </Flex>
            <Dialog.Close>
              <IconButton variant="ghost" color="gray" aria-label="Close">
                <X size={16} />
              </IconButton>
            </Dialog.Close>
          </Flex>

          {hasParsedNotes || isPendingReleases ? (
            <Flex direction="column" gap="2">
              <Text
                size="1"
                weight="medium"
                color="gray"
                className="uppercase tracking-wide"
              >
                Release notes
              </Text>
              {hasParsedNotes && parsedNotes ? (
                <ScrollArea
                  type="auto"
                  scrollbars="vertical"
                  style={{ maxHeight: 240 }}
                >
                  <div className="pr-3">
                    <ReleaseNotesSections notes={parsedNotes} />
                  </div>
                </ScrollArea>
              ) : (
                <ReleaseNotesSkeleton />
              )}
            </Flex>
          ) : null}

          {isDownloading ? (
            <Flex direction="column" gap="1">
              <Flex justify="between">
                <Text size="1" color="gray">
                  Downloading... {percent}%
                </Text>
                <Text size="1" color="gray">
                  {formatSpeed(bytesPerSecond)}
                </Text>
              </Flex>
              <Progress value={percent} size="2" />
            </Flex>
          ) : null}

          <Flex justify="end" align="center" gap="2" mt="1">
            <Button variant="soft" color="gray" size="2" onClick={close}>
              Later
            </Button>
            {isReady ? (
              <Button size="2" onClick={() => void installUpdate()}>
                Restart to update
              </Button>
            ) : isDownloading ? (
              <Button size="2" disabled>
                Downloading...
              </Button>
            ) : (
              <Button
                size="2"
                onClick={() => downloadMutation.mutate(undefined)}
                disabled={downloadMutation.isPending}
              >
                Download update
              </Button>
            )}
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
