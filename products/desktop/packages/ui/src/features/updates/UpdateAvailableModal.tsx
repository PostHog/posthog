import { useHostTRPC } from "@posthog/host-router/react";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Progress,
  ScrollArea,
  Skeleton,
  Text,
} from "@posthog/quill";
import { useBlockingAnnouncementVisible } from "@posthog/ui/features/announcements/useAnnouncementVisible";
import { ReleaseNotesSections } from "@posthog/ui/features/updates/ReleaseNotesSections";
import { parseReleaseNotes } from "@posthog/ui/features/updates/releaseNotes";
import { useUpdateModalStore } from "@posthog/ui/features/updates/updateModalStore";
import {
  useHasActiveUpdate,
  useInstallUpdate,
  useUpdateView,
} from "@posthog/ui/features/updates/updateStore";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

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
    <div className="flex flex-col gap-3">
      {["improved", "fixed"].map((key) => (
        <div key={key} className="flex flex-col gap-2">
          <Skeleton className="h-3 w-14" />
          <Skeleton className="h-3.5 w-[90%]" />
          <Skeleton className="h-3.5 w-[80%]" />
        </div>
      ))}
    </div>
  );
}

export function UpdateAvailableModal() {
  const isOpen = useUpdateModalStore((state) => state.isOpen);
  const close = useUpdateModalStore((state) => state.close);
  const blockingAnnouncementVisible = useBlockingAnnouncementVisible();

  useEffect(() => {
    if (isOpen && blockingAnnouncementVisible) close();
  }, [isOpen, blockingAnnouncementVisible, close]);
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
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="max-w-[440px]">
        <DialogHeader>
          <DialogTitle>
            {isReady ? "Update ready" : "Update available"}
          </DialogTitle>
          <DialogDescription>
            {targetVersion
              ? `PostHog ${targetVersion}${sizeLabel ? ` · ${sizeLabel}` : ""}`
              : "A new version is available"}
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-4">
          {hasParsedNotes || isPendingReleases ? (
            <div className="flex flex-col gap-2">
              <Text
                size="xs"
                weight="medium"
                variant="muted"
                className="uppercase tracking-wide"
              >
                Release notes
              </Text>
              {hasParsedNotes && parsedNotes ? (
                <ScrollArea className="max-h-60">
                  <div className="pr-3">
                    <ReleaseNotesSections notes={parsedNotes} />
                  </div>
                </ScrollArea>
              ) : (
                <ReleaseNotesSkeleton />
              )}
            </div>
          ) : null}

          {isDownloading ? (
            <div className="flex flex-col gap-1">
              <div className="flex justify-between">
                <Text size="xs" variant="muted">
                  Downloading... {percent}%
                </Text>
                <Text size="xs" variant="muted">
                  {formatSpeed(bytesPerSecond)}
                </Text>
              </div>
              <Progress value={percent} />
            </div>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={close}>
            Later
          </Button>
          {isReady ? (
            <Button variant="primary" onClick={() => void installUpdate()}>
              Restart to update
            </Button>
          ) : isDownloading ? (
            <Button variant="primary" disabled>
              Downloading...
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => downloadMutation.mutate(undefined)}
              disabled={downloadMutation.isPending}
              loading={downloadMutation.isPending}
            >
              Download update
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
