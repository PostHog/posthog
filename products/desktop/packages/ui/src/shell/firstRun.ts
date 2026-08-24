import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { ProvisionedTaskChannels } from "@posthog/shared/domain-types";

export type FirstRunClient = Pick<
  PostHogAPIClient,
  "provisionDefaultTaskChannels" | "startOnboardingSession"
>;

export interface FirstRun {
  /** ``null`` when provisioning failed, which must not stop the app opening. */
  provisioned: Promise<ProvisionedTaskChannels | null>;
  /** ``null`` unless this is the first run and the backend opened a session. */
  sessionTaskId: Promise<string | null>;
}

/**
 * Only #general is proof: creating a task without one ensures the personal space, so a user who
 * reached the composer before provisioning ran has a personal space that provisioning did not
 * create and reports `personal_created: false`.
 */
export function isFirstRun(
  provisioned: ProvisionedTaskChannels | null,
): boolean {
  return Boolean(provisioned?.general_created || provisioned?.personal_created);
}

let started: (FirstRun & { identity: string }) | null = null;

function begin(identity: string, client: FirstRunClient): FirstRun {
  const provisioned = client.provisionDefaultTaskChannels().catch(() => {
    // Dropped so a later caller provisions again rather than inheriting the failure.
    if (started?.identity === identity) started = null;
    return null;
  });
  const entry = {
    identity,
    provisioned,
    // Its own promise, not awaited into `provisioned`, so a hung scrape cannot hold up
    // the callers that only need the channels.
    sessionTaskId: provisioned.then((channels) =>
      isFirstRun(channels)
        ? client.startOnboardingSession().catch(() => null)
        : null,
    ),
  };
  started = entry;
  return entry;
}

/**
 * Start provisioning and, on a first run, the session the user will land in. Called as soon as
 * the user is through the access check, so the work overlaps onboarding instead of following it.
 */
export function beginFirstRun(identity: string, client: FirstRunClient): void {
  if (started?.identity !== identity) begin(identity, client);
}

/**
 * The result of {@link beginFirstRun}, shared rather than consumed: `personal_created` and
 * `general_created` are true only for whoever provisions first, so every reader has to see the
 * same response or the later ones decide this is not a first run.
 */
export function firstRun(identity: string, client: FirstRunClient): FirstRun {
  return started?.identity === identity ? started : begin(identity, client);
}
