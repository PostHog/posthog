import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { showChannelList } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useSpaceTreeStore } from "@posthog/ui/features/canvas/stores/spaceTreeStore";
import { router } from "@posthog/ui/router/router";
import { logger } from "@posthog/ui/shell/logger";
import {
  rememberStartupLocation,
  resolveStartupLocation,
} from "@posthog/ui/shell/startupLocation";
import { type RefObject, useEffect, useState } from "react";

const log = logger.scope("app");

interface InitialRouteInput {
  readyForMainApp: boolean;
  startupIdentity: string | null;
  authenticatedClient: PostHogAPIClient | null;
  spacesLayoutEnabledRef: RefObject<boolean>;
}

/**
 * Resolves and loads the initial route before the router mounts, and keeps the
 * remembered startup location current afterwards. Resets when the user leaves
 * the main app so a later re-entry starts fresh.
 */
export function useInitialRoute({
  readyForMainApp,
  startupIdentity,
  authenticatedClient,
  spacesLayoutEnabledRef,
}: InitialRouteInput): boolean {
  const [initialRouteLoaded, setInitialRouteLoaded] = useState(false);

  useEffect(() => {
    if (!readyForMainApp) {
      setInitialRouteLoaded(false);
      return;
    }
    if (initialRouteLoaded) return;
    if (!startupIdentity || !authenticatedClient) return;

    let cancelled = false;
    const loadInitialRoute = async (): Promise<void> => {
      try {
        const { href, firstRun } = await resolveStartupLocation(
          startupIdentity,
          authenticatedClient,
          spacesLayoutEnabledRef.current,
        );
        if (firstRun) {
          showChannelList({ keepForRoute: firstRun.generalChannelId });
          useSpaceTreeStore.getState().expandSpace(firstRun.generalChannelId);
        }
        router.history.replace(href);
        rememberStartupLocation(startupIdentity, href);
        await router.load();
      } catch (error) {
        log.error("Failed to load initial route", { error });
      } finally {
        if (!cancelled) setInitialRouteLoaded(true);
      }
    };
    void loadInitialRoute();

    return () => {
      cancelled = true;
    };
  }, [
    readyForMainApp,
    initialRouteLoaded,
    startupIdentity,
    authenticatedClient,
    spacesLayoutEnabledRef,
  ]);

  useEffect(() => {
    if (!initialRouteLoaded || !startupIdentity) return;
    return router.history.subscribe(({ location }) => {
      rememberStartupLocation(startupIdentity, location.href);
    });
  }, [initialRouteLoaded, startupIdentity]);

  return initialRouteLoaded;
}
