import { X } from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Skeleton,
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
      <DialogContent showCloseButton={false} className="max-w-[640px]">
        <DialogHeader className="flex-row items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <DialogTitle>What's New</DialogTitle>
            <DialogDescription>
              Release history and recent improvements
            </DialogDescription>
          </div>
          <DialogClose
            render={
              <Button variant="link-muted" size="icon" aria-label="Close" />
            }
          >
            <X size={16} />
          </DialogClose>
        </DialogHeader>

        <DialogBody className="max-h-[60vh] overflow-y-auto pr-3">
          {isError ? (
            <p className="text-(--gray-11) text-sm">
              Could not load releases. Please try again later.
            </p>
          ) : isPending ? (
            <ChangelogSkeleton />
          ) : groups.length === 0 ? (
            <p className="text-(--gray-11) text-sm">No releases found.</p>
          ) : (
            <div className="flex flex-col gap-5">
              {groups.map((group, index) => {
                const { improved, fixed } = mergeReleaseNotes(group.releases);
                const containsCurrent = currentVersion
                  ? group.releases.some(
                      (release) => release.version === currentVersion,
                    )
                  : false;
                return (
                  <section
                    key={group.key}
                    className={
                      index > 0 ? "border-gray-6 border-t pt-5" : undefined
                    }
                  >
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <h2 className="font-bold text-base">{group.label}</h2>
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
                      <p className="text-(--gray-11) text-sm">
                        No notable changes.
                      </p>
                    ) : (
                      <ReleaseNotesSections notes={{ improved, fixed }} />
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
