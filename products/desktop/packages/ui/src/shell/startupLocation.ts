import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<PostHogAPIClient, "getTaskChannels">;

const storageKey = (identity: string): string => `startup-location:${identity}`;

export async function resolveStartupLocation(
  identity: string,
  client: StartupLocationClient,
): Promise<string> {
  const saved = await stateStorage.getItem(storageKey(identity));
  if (saved) return saved;
  const personal = (await client.getTaskChannels()).find(
    (channel) => channel.channel_type === "personal",
  );
  if (!personal) throw new Error("Personal channel was not provisioned");
  return `/website/${personal.id}/new`;
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
