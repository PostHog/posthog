import { DiscordLogo, Warning } from "@phosphor-icons/react";
import { updateStore } from "@posthog/core/updates/updateStore";
import { useHostTRPC } from "@posthog/host-router/react";
import { EXTERNAL_LINKS } from "@posthog/shared";
import { useBusyLocalSessionCount } from "@posthog/ui/features/sessions/useBusyLocalSessionCount";
import { ReleaseNotesSections } from "@posthog/ui/features/updates/ReleaseNotesSections";
import {
  mergeReleaseNotes,
  parseReleaseNotes,
  releasesBetween,
} from "@posthog/ui/features/updates/releaseNotes";
import {
  useInstallUpdate,
  useUpdateView,
} from "@posthog/ui/features/updates/updateStore";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Button, Flex, ScrollArea, Skeleton, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";

function NotesSkeleton() {
  return (
    <Flex direction="column" gap="2">
      <Skeleton width="56px" height="12px" />
      <Skeleton width="90%" height="14px" />
      <Skeleton width="80%" height="14px" />
      <Skeleton width="85%" height="14px" />
    </Flex>
  );
}

/**
 * The expanded "Restart to apply" panel: what shipped since the version the
 * user is running, whether a restart would interrupt working agents, and the
 * restart-now / restart-when-idle actions.
 */
export function UpdateReadyPeek() {
  const {
    version,
    currentVersion,
    releaseNotes,
    deferredInstallPhase,
    deferredInstallCountdown,
  } = useUpdateView();
  const installUpdate = useInstallUpdate();
  const openWhatsNew = useWhatsNewStore((state) => state.open);
  const busyAgents = useBusyLocalSessionCount();
  const hostTRPC = useHostTRPC();
  const { data: releasesData, isPending: isPendingReleases } = useQuery(
    hostTRPC.releaseFeed.list.queryOptions(
      version ? { expectVersion: version } : undefined,
    ),
  );

  const releases = releasesData?.releases ?? [];
  const delta = version
    ? releasesBetween(releases, currentVersion, version)
    : [];
  const mergedNotes = mergeReleaseNotes(delta);
  // The feed can lag a fresh release; fall back to the updater's own notes.
  const notes =
    mergedNotes.improved.length > 0 || mergedNotes.fixed.length > 0
      ? mergedNotes
      : releaseNotes
        ? parseReleaseNotes(releaseNotes)
        : null;
  const hasNotes =
    !!notes && (notes.improved.length > 0 || notes.fixed.length > 0);
  const behindCount = currentVersion ? delta.length : 0;

  const isArmed = deferredInstallPhase !== "off";

  return (
    <Flex direction="column" gap="3" className="w-[320px]">
      <Flex direction="column" gap="0">
        <Text className="font-medium text-(--gray-12) text-[13px]">
          {version ? `PostHog ${version} is ready` : "Update ready"}
        </Text>
        <Text className="text-(--gray-10) text-[12px]">
          {currentVersion
            ? `You're on ${currentVersion}${
                behindCount > 0
                  ? ` — ${behindCount} release${behindCount === 1 ? "" : "s"} behind`
                  : ""
              }`
            : "Restart to apply the update"}
        </Text>
      </Flex>

      {isPendingReleases && !hasNotes ? (
        <NotesSkeleton />
      ) : hasNotes && notes ? (
        <ScrollArea
          type="auto"
          scrollbars="vertical"
          style={{ maxHeight: 260 }}
        >
          <div className="pr-3">
            <ReleaseNotesSections notes={notes} />
          </div>
        </ScrollArea>
      ) : (
        <Text className="text-(--gray-10) text-[12px]">
          No release notes available.
        </Text>
      )}

      {busyAgents > 0 && !isArmed ? (
        <Flex gap="2" className="rounded-md bg-(--amber-a3) p-2">
          <Warning size={14} className="mt-px shrink-0 text-(--amber-11)" />
          <Text className="text-(--amber-11) text-[12px]">
            {busyAgents === 1 ? "1 agent is" : `${busyAgents} agents are`} still
            working — restarting now interrupts{" "}
            {busyAgents === 1 ? "it" : "them"}. Cloud tasks keep running.
          </Text>
        </Flex>
      ) : null}

      {isArmed ? (
        <Flex
          align="center"
          justify="between"
          gap="2"
          className="rounded-md bg-(--green-a3) p-2"
        >
          <Text className="text-(--green-11) text-[12px]">
            {deferredInstallPhase === "countdown" &&
            deferredInstallCountdown !== null
              ? `Restarting in ${deferredInstallCountdown}s…`
              : "Restarting once agents finish"}
          </Text>
          <Button
            size="1"
            variant="soft"
            color="gray"
            onClick={() => updateStore.getState().disarmDeferredInstall()}
          >
            Cancel
          </Button>
        </Flex>
      ) : (
        <Flex gap="2">
          {busyAgents > 0 ? (
            <>
              <Button
                size="1"
                className="flex-1"
                onClick={() => updateStore.getState().armDeferredInstall()}
              >
                Restart when agents finish
              </Button>
              <Button
                size="1"
                variant="soft"
                color="gray"
                onClick={() => void installUpdate()}
              >
                Restart now
              </Button>
            </>
          ) : (
            <Button
              size="1"
              className="flex-1"
              onClick={() => void installUpdate()}
            >
              Restart now
            </Button>
          )}
        </Flex>
      )}

      <Flex
        align="center"
        justify="between"
        className="border-(--gray-4) border-t pt-2"
      >
        <Text className="text-(--gray-9) text-[11px]">
          Also applies next time you quit
        </Text>
        <Flex align="center" gap="3">
          <button
            type="button"
            className="text-(--gray-10) text-[11px] transition-colors hover:text-(--gray-12)"
            onClick={openWhatsNew}
          >
            Full changelog
          </button>
          <button
            type="button"
            className="flex items-center gap-1 text-(--gray-10) text-[11px] transition-colors hover:text-(--gray-12)"
            onClick={() => openExternalUrl(EXTERNAL_LINKS.discord)}
          >
            <DiscordLogo size={12} />
            Feedback
          </button>
        </Flex>
      </Flex>
    </Flex>
  );
}
