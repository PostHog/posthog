import {
  ensurePersonalChannelFromClient,
  type PersonalChannelClient,
} from "@posthog/ui/features/canvas/ensurePersonalChannel";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

const storageKey = (identity: string): string => `startup-location:${identity}`;

export async function resolveStartupLocation(
  identity: string,
  client: PersonalChannelClient,
): Promise<string> {
  const saved = await stateStorage.getItem(storageKey(identity));
  if (saved) return saved;
  const personal = await ensurePersonalChannelFromClient(client);
  return `/website/${personal.id}/new`;
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
