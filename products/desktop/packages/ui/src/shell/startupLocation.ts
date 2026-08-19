import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { isGeneralChannel } from "@posthog/core/canvas/channelName";
import type { ProvisionedTaskChannels } from "@posthog/shared/domain-types";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<
  PostHogAPIClient,
  "provisionDefaultTaskChannels"
>;

const storageKey = (identity: string): string => `startup-location:${identity}`;

interface StartupLocation {
  href: string;
  /** Set on a first-run landing so the caller can prime the sidebar. */
  firstRun: { generalChannelId: string } | null;
}

let primedProvision: ProvisionedTaskChannels | null = null;

/**
 * Hand a provisioning result to the startup resolver. Whoever provisions first
 * consumes the created flags, so a flow that provisions before the main app
 * mounts (onboarding completion) must pass its result along for the first-run
 * decision instead of letting startup re-provision and read false flags.
 */
export function primeStartupProvision(result: ProvisionedTaskChannels): void {
  primedProvision = result;
}

export async function resolveStartupLocation(
  identity: string,
  client: StartupLocationClient,
): Promise<StartupLocation> {
  const saved = await stateStorage.getItem(storageKey(identity));
  if (saved) return { href: saved, firstRun: null };

  const provisioned =
    primedProvision ?? (await client.provisionDefaultTaskChannels());
  primedProvision = null;
  const general = provisioned.channels.find((channel) =>
    isGeneralChannel(channel),
  );
  if (!general) throw new Error("#general was not provisioned");

  // First run means the user's default spaces did not exist until now, as
  // reported by the server. A reinstall or new machine only loses the saved
  // location, so it lands on #general without the first-run treatment.
  const isFirstRun =
    provisioned.personal_created || provisioned.general_created;
  return {
    href: `/website/${general.id}`,
    firstRun: isFirstRun ? { generalChannelId: general.id } : null,
  };
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
