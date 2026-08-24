import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { isGeneralChannel } from "@posthog/core/canvas/channelName";
import type { ProvisionedTaskChannels } from "@posthog/shared/domain-types";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

type StartupLocationClient = Pick<
  PostHogAPIClient,
  "provisionDefaultTaskChannels" | "startOnboardingSession"
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
  // channels.
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

/**
 * The session normally lands well before the loading screen goes away, so waiting for it buys
 * opening straight into it rather than into an empty feed. The cap is what stops a slow or hung
 * scrape holding the app shut: past it the feed opens, and the session shows up there instead.
 */
const SESSION_WAIT_MS = 15_000;

async function startedSessionTaskId(
  client: StartupLocationClient,
): Promise<string | null> {
  return Promise.race([
    client.startOnboardingSession().catch(() => null),
    new Promise<null>((resolve) =>
      setTimeout(() => resolve(null), SESSION_WAIT_MS),
    ),
  ]);
}

export async function resolveStartupLocation(
  identity: string,
  client: StartupLocationClient,
  spacesEnabled: boolean,
): Promise<StartupLocation> {
  // Provisioning is what says whether this is a first run, so it runs before anything else looks
  // at where the user was last. A saved location is written on every navigation and is shared by
  // every account on the project, so it answers neither question reliably.
  // Provisioning is what says whether this is a first run, so it runs before anything looks at
  // where the user was last. It must not decide whether they can open the app at all, though.
  const provisioned = await consumePrimedProvision(identity, client).catch(
    () => null,
  );

  // The old key predates the created flags, so its presence is the only proof this install was
  // in use before the default spaces existed. That outranks the flags: provisioning a long-time
  // user's spaces for the first time reports a first run, and they are not new.
  const legacy = await stateStorage.getItem(legacyStorageKey(identity));
  if (legacy) {
    if (provisioned) void stateStorage.removeItem(legacyStorageKey(identity));
    return { href: rewriteLegacyHref(legacy), firstRun: null };
  }

  const isFirstRun =
    provisioned?.personal_created || provisioned?.general_created;

  if (!isFirstRun) {
    const saved = await stateStorage.getItem(storageKey(identity));
    if (saved) return { href: rewriteLegacyHref(saved), firstRun: null };
  }
  if (!provisioned) throw new Error("#general was not provisioned");

  const general = provisioned.channels.find((channel) =>
    isGeneralChannel(channel),
  );
  if (!general) throw new Error("#general was not provisioned");

  // /website renders WebsiteLayout, which suppresses ContentHeader and hides the Channels
  // toggle, and the route stays registered whether or not the layout is on. Sending someone
  // there before we know they can leave again is how a first run strands with no way back;
  // /code is navigable either way. An uncached flag reads false here, so a flag-on user can
  // land on /code once, which costs them a click rather than the session.
  if (!spacesEnabled) return { href: "/code", firstRun: null };

  const sessionTaskId = provisioned.personal_created
    ? await startedSessionTaskId(client)
    : null;
  return {
    href: sessionTaskId
      ? `/spaces/${general.id}/tasks/${sessionTaskId}`
      : `/spaces/${general.id}`,
    firstRun: isFirstRun ? { generalChannelId: general.id } : null,
  };
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
