import { X } from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { useBillingAnnouncementVisible } from "@posthog/ui/features/billing/useBillingAnnouncementVisible";
import { ReleaseNotesSections } from "@posthog/ui/features/updates/ReleaseNotesSections";
import {
  groupReleases,
  mergeReleaseNotes,
} from "@posthog/ui/features/updates/releaseNotes";
import { useHasActiveUpdate } from "@posthog/ui/features/updates/updateStore";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import {
  Badge,
  Dialog,
  Flex,
  IconButton,
  ScrollArea,
  Skeleton,
  Text,
} from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";

function ChangelogSkeleton() {
  return (
    <Flex direction="column" gap="5">
      {["a", "b", "c"].map((key) => (
        <Flex key={key} direction="column" gap="3">
          <Flex align="center" justify="between" gap="2">
            <Skeleton width="150px" height="22px" />
            <Skeleton width="72px" height="22px" />
          </Flex>
          <Flex direction="column" gap="2">
            <Skeleton width="64px" height="12px" />
            <Skeleton width="82%" height="14px" />
            <Skeleton width="68%" height="14px" />
            <Skeleton width="74%" height="14px" />
          </Flex>
        </Flex>
      ))}
    </Flex>
  );
}

export function WhatsNewModal() {
  const isOpen = useWhatsNewStore((state) => state.isOpen);
  const close = useWhatsNewStore((state) => state.close);
  // The blocking billing announcement takes the stage alone — the post-update
  // auto-open waits here until it's acknowledged, then appears.
  const billingAnnouncementVisible = useBillingAnnouncementVisible();
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
    <Dialog.Root
      open={isOpen && !billingAnnouncementVisible}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Dialog.Content maxWidth="640px">
        <Flex justify="between" align="start" gap="3" mb="3">
          <Flex direction="column" gap="1">
            <Dialog.Title className="mb-0">What's New</Dialog.Title>
            <Dialog.Description>
              <Text color="gray" size="2">
                Release history and recent improvements
              </Text>
            </Dialog.Description>
          </Flex>
          <Dialog.Close>
            <IconButton variant="ghost" color="gray" aria-label="Close">
              <X size={16} />
            </IconButton>
          </Dialog.Close>
        </Flex>

        {isError ? (
          <Text color="gray" size="2">
            Could not load releases. Please try again later.
          </Text>
        ) : isPending ? (
          <ChangelogSkeleton />
        ) : groups.length === 0 ? (
          <Text color="gray" size="2">
            No releases found.
          </Text>
        ) : (
          <ScrollArea
            type="scroll"
            scrollbars="vertical"
            style={{ maxHeight: "60vh" }}
          >
            <Flex direction="column" gap="5" className="pr-3">
              {groups.map((group, index) => {
                const { improved, fixed } = mergeReleaseNotes(group.releases);
                const containsCurrent = currentVersion
                  ? group.releases.some(
                      (release) => release.version === currentVersion,
                    )
                  : false;
                return (
                  <Flex
                    key={group.key}
                    direction="column"
                    gap="3"
                    className={
                      index > 0 ? "border-gray-6 border-t pt-5" : undefined
                    }
                  >
                    <Flex align="center" justify="between" gap="2">
                      <Text weight="bold" size="3">
                        {group.label}
                      </Text>
                      <Flex align="center" gap="2">
                        {group.isLatest ? (
                          <Badge color="green">Latest</Badge>
                        ) : null}
                        {containsCurrent ? (
                          <Badge color="gray" variant="outline">
                            Current
                          </Badge>
                        ) : null}
                        <Badge color="gray" variant="soft">
                          {group.releases.length === 1
                            ? group.releases[0].name
                            : `${group.releases.length} releases`}
                        </Badge>
                      </Flex>
                    </Flex>
                    {improved.length === 0 && fixed.length === 0 ? (
                      <Text size="2" color="gray">
                        No notable changes.
                      </Text>
                    ) : (
                      <ReleaseNotesSections notes={{ improved, fixed }} />
                    )}
                  </Flex>
                );
              })}
            </Flex>
          </ScrollArea>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
