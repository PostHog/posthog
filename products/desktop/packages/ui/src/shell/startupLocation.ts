import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  isGeneralChannel,
  isPersonalChannel,
} from "@posthog/core/canvas/channelName";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<PostHogAPIClient, "getTaskChannels">;

const storageKey = (identity: string): string => `startup-location:${identity}`;

interface StartupLocation {
  href: string;
  /** Set on a first-run landing so the caller can prime the sidebar. */
  firstRun: { generalChannelId: string } | null;
}

export async function resolveStartupLocation(
  identity: string,
  client: StartupLocationClient,
): Promise<StartupLocation> {
  const saved = await stateStorage.getItem(storageKey(identity));
  if (saved) return { href: saved, firstRun: null };
  const channels = await client.getTaskChannels();
  // Personal fallback covers a server that does not provision #general yet.
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (general) {
    return {
      href: `/website/${general.id}`,
      firstRun: { generalChannelId: general.id },
    };
  }
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (!personal) throw new Error("Personal channel was not provisioned");
  return { href: `/website/${personal.id}/new`, firstRun: null };
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
