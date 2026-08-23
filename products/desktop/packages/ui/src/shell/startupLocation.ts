import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { isGeneralChannel } from "@posthog/core/canvas/channelName";
import type { ProvisionedTaskChannels } from "@posthog/shared/domain-types";
import { rewriteLegacyHref } from "@posthog/ui/router/legacyPaths";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<
  PostHogAPIClient,
  "provisionDefaultTaskChannels"
>;

const storageKey = (identity: string): string =>
  `startup-location:v2:${identity}`;
/** Where installs from before the default spaces existed kept their location. */
const legacyStorageKey = (identity: string): string =>
  `startup-location:${identity}`;

interface StartupLocation {
  href: string;
  firstRun: { generalChannelId: string } | null;
}

let primedProvision: {
  identity: string;
  result: Promise<ProvisionedTaskChannels>;
} | null = null;

/**
 * Whoever provisions first consumes the created flags, so a flow that provisions
 * before the app mounts has to hand its result over rather than let startup
 * provision again and read false flags. The in-flight promise is handed over
 * (not the resolved value) so the hand-off wins the race synchronously, before
 * the caller mounts the app, even while the network call is still pending.
 */
export function primeStartupProvision(
  identity: string,
  result: Promise<ProvisionedTaskChannels>,
): void {
  primedProvision = { identity, result };
}

async function consumePrimedProvision(
  identity: string,
  client: StartupLocationClient,
): Promise<ProvisionedTaskChannels> {
  const primed = primedProvision;
  primedProvision = null;
  // Keyed by identity because a logout or account switch between priming and
  // consuming would otherwise hand the next account the previous project's
  // channels. Everything else in this module is already keyed the same way.
  if (primed && primed.identity === identity) {
    try {
      return await primed.result;
    } catch {
      // A failed hand-off must not cost the user their provisioning, so fall
      // back to provisioning here as if nothing had been primed.
    }
  }
  return client.provisionDefaultTaskChannels();
}

export async function resolveStartupLocation(
  identity: string,
  client: StartupLocationClient,
): Promise<StartupLocation> {
  const saved = await stateStorage.getItem(storageKey(identity));
  if (saved) return { href: rewriteLegacyHref(saved), firstRun: null };

  const legacy = await stateStorage.getItem(legacyStorageKey(identity));
  if (legacy) {
    // Provisioning does not get to decide whether someone who was already using
    // the app can open it. Keeping the old key retries on the next launch.
    try {
      await client.provisionDefaultTaskChannels();
      void stateStorage.removeItem(legacyStorageKey(identity));
    } catch {}
    return { href: rewriteLegacyHref(legacy), firstRun: null };
  }

  const provisioned = await consumePrimedProvision(identity, client);
  const general = provisioned.channels.find((channel) =>
    isGeneralChannel(channel),
  );
  if (!general) throw new Error("#general was not provisioned");

  // A reinstall or a new machine loses only the saved location, so the created
  // flags decide this rather than the absence of one.
  const isFirstRun =
    provisioned.personal_created || provisioned.general_created;
  return {
    href: `/spaces/${general.id}`,
    firstRun: isFirstRun ? { generalChannelId: general.id } : null,
  };
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
