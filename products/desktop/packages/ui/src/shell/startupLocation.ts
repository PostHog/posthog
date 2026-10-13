import { isGeneralChannel } from "@posthog/core/canvas/channelName";
import { rewriteLegacyHref } from "@posthog/ui/router/legacyPaths";
import {
  ensureSession,
  type FirstRunClient,
  firstRun,
  isFirstRun,
} from "@posthog/ui/shell/firstRun";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";

const storageKey = (identity: string): string =>
  `startup-location:v2:${identity}`;
/** Where installs from before the default spaces existed kept their location. */
const legacyStorageKey = (identity: string): string =>
  `startup-location:${identity}`;

interface StartupLocation {
  href: string;
  firstRun: { generalChannelId: string } | null;
}

/**
 * The session starts as soon as consent permits and normally settles while onboarding is still on
 * screen, so this wait is only ever paid by someone who got through onboarding faster than the
 * scrape. The cap is what stops a hung one holding the app shut: past it the feed opens, and the
 * session shows up there instead.
 */
const SESSION_WAIT_MS = 15_000;

async function cappedSessionTaskId(
  sessionTaskId: Promise<string | null>,
): Promise<string | null> {
  return Promise.race([
    sessionTaskId,
    new Promise<null>((resolve) =>
      setTimeout(() => resolve(null), SESSION_WAIT_MS),
    ),
  ]);
}

export async function resolveStartupLocation(
  identity: string,
  client: FirstRunClient,
  spacesEnabled: boolean,
): Promise<StartupLocation> {
  // Provisioning is what says whether this is a first run, so it is read before anything looks at
  // where the user was last. A saved location is written on every navigation and is shared by every
  // account on the project, so it answers neither question reliably.
  const run = firstRun(identity, client);
  const sessionTaskIdPromise = ensureSession(identity, client);
  const provisioned = await run.provisioned;

  // The old key predates the created flags, so its presence is the only proof this install was
  // in use before the default spaces existed. That outranks the flags: provisioning a long-time
  // user's spaces for the first time reports a first run, and they are not new.
  const legacy = await stateStorage.getItem(legacyStorageKey(identity));
  if (legacy) {
    if (provisioned) void stateStorage.removeItem(legacyStorageKey(identity));
    return { href: rewriteLegacyHref(legacy), firstRun: null };
  }

  const firstRunHere = isFirstRun(provisioned);

  if (!firstRunHere) {
    const saved = await stateStorage.getItem(storageKey(identity));
    if (saved) return { href: rewriteLegacyHref(saved), firstRun: null };
  }
  if (!provisioned) return { href: "/code", firstRun: null };

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

  const sessionTaskId = await cappedSessionTaskId(sessionTaskIdPromise);
  return {
    href: sessionTaskId
      ? `/spaces/${general.id}/tasks/${sessionTaskId}`
      : `/spaces/${general.id}`,
    firstRun: firstRunHere ? { generalChannelId: general.id } : null,
  };
}

export function rememberStartupLocation(identity: string, href: string): void {
  void stateStorage.setItem(storageKey(identity), href);
}
