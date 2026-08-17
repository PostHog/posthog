import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  isGeneralChannel,
  isPersonalChannel,
} from "@posthog/core/canvas/channelName";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<PostHogAPIClient, "getTaskChannels">;

const storageKey = (identity: string): string => `startup-location:${identity}`;

export async function resolveStartupLocation(
  identity: string,
  client: StartupLocationClient,
): Promise<string> {
  const saved = await stateStorage.getItem(storageKey(identity));
  if (saved) return saved;
  const channels = await client.getTaskChannels();
  // #general is the new default landing space; fall back to the personal channel
  // for a server that hasn't been upgraded to provision #general yet.
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (general) return `/website/${general.id}/new`;
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (!personal) throw new Error("Personal channel was not provisioned");
  return `/website/${personal.id}/new`;
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
