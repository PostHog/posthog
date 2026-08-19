import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  isGeneralChannel,
  isPersonalChannel,
} from "@posthog/core/canvas/channelName";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<
  PostHogAPIClient,
  "getTaskChannels" | "provisionDefaultTaskChannels"
>;

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
  // Listing is a pure read; a first run (or a pre-#general team) provisions
  // the default spaces explicitly and lands on the fresh list.
  let channels = await client.getTaskChannels();
  if (
    !channels.some((channel) => isPersonalChannel(channel)) ||
    !channels.some((channel) => isGeneralChannel(channel))
  ) {
    channels = (await client.provisionDefaultTaskChannels()).channels;
  }
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (general) {
    return {
      href: `/website/${general.id}`,
      firstRun: { generalChannelId: general.id },
    };
  }
  // Defensive: land somewhere sensible even if provisioning returned no #general.
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (!personal) throw new Error("Personal channel was not provisioned");
  return { href: `/website/${personal.id}/new`, firstRun: null };
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
