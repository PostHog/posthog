import { useHostTRPC } from "@posthog/host-router/react";
import {
  Badge,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  ScrollArea,
  Skeleton,
  Text,
} from "@posthog/quill";
import { ReleaseNotesSections } from "@posthog/ui/features/updates/ReleaseNotesSections";
import {
  groupReleases,
  mergeReleaseNotes,
} from "@posthog/ui/features/updates/releaseNotes";
import { useHasActiveUpdate } from "@posthog/ui/features/updates/updateStore";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { useQuery } from "@tanstack/react-query";

function ChangelogSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      {["a", "b", "c"].map((key) => (
        <div key={key} className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <Skeleton className="h-[22px] w-[150px]" />
            <Skeleton className="h-[22px] w-[72px]" />
          </div>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3.5 w-[82%]" />
            <Skeleton className="h-3.5 w-[68%]" />
            <Skeleton className="h-3.5 w-[74%]" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function WhatsNewModal() {
  const isOpen = useWhatsNewStore((state) => state.isOpen);
  const close = useWhatsNewStore((state) => state.close);
  const prefetchForActiveUpdate = useHasActiveUpdate();
  const hostTRPC = useHostTRPC();
  const { data: currentVersion, isError: isVersionError } = useQuery(
    hostTRPC.os.getAppVersion.queryOptions(),
  );
  const {
    data,
    isPending,
    isError: isReleasesError,
  } = useQuery({
    ...hostTRPC.releaseFeed.list.queryOptions(
      currentVersion ? { expectVersion: currentVersion } : undefined,
    ),
    enabled: (isOpen || prefetchForActiveUpdate) && !!currentVersion,
  });
  const isError = isVersionError || isReleasesError;

  const groups = groupReleases(data?.releases ?? []);

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="max-w-[640px]">
        <DialogHeader>
          <DialogTitle>What's New</DialogTitle>
          <DialogDescription>
            Release history and recent improvements
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          {isError ? (
            <Text size="sm" variant="muted">
              Could not load releases. Please try again later.
            </Text>
          ) : isPending ? (
            <ChangelogSkeleton />
          ) : groups.length === 0 ? (
            <Text size="sm" variant="muted">
              No releases found.
            </Text>
          ) : (
            <ScrollArea className="max-h-[60vh]">
              <div className="flex flex-col gap-5 pr-3">
                {groups.map((group, index) => {
                  const { improved, fixed } = mergeReleaseNotes(group.releases);
                  const containsCurrent = currentVersion
                    ? group.releases.some(
                        (release) => release.version === currentVersion,
                      )
                    : false;
                  return (
                    <div
                      key={group.key}
                      className={
                        index > 0 ? "border-gray-6 border-t pt-5" : undefined
                      }
                    >
                      <div className="flex flex-col gap-3">
                        <div className="flex items-center justify-between gap-2">
                          <Text weight="semibold">{group.label}</Text>
                          <div className="flex items-center gap-2">
                            {group.isLatest ? (
                              <Badge variant="success">Latest</Badge>
                            ) : null}
                            {containsCurrent ? <Badge>Current</Badge> : null}
                            <Badge>
                              {group.releases.length === 1
                                ? group.releases[0].name
                                : `${group.releases.length} releases`}
                            </Badge>
                          </div>
                        </div>
                        {improved.length === 0 && fixed.length === 0 ? (
                          <Text size="sm" variant="muted">
                            No notable changes.
                          </Text>
                        ) : (
                          <ReleaseNotesSections notes={{ improved, fixed }} />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
