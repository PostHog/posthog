import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { ProvisionedTaskChannels } from "@posthog/shared/domain-types";

export type FirstRunClient = Pick<
  PostHogAPIClient,
  "provisionDefaultTaskChannels" | "startOnboardingSession"
>;

export interface FirstRun {
  /** ``null`` when provisioning failed, which must not stop the app opening. */
  provisioned: Promise<ProvisionedTaskChannels | null>;
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

type FirstRunEntry = FirstRun & {
  identity: string;
  sessionTaskId?: Promise<string | null>;
};

let started: FirstRunEntry | null = null;

function begin(identity: string, client: FirstRunClient): FirstRunEntry {
  const provisioned = client.provisionDefaultTaskChannels().catch(() => {
    // Dropped so a later caller provisions again rather than inheriting the failure.
    if (started?.identity === identity) started = null;
    return null;
  });
  const entry: FirstRunEntry = {
    identity,
    provisioned,
  };
  started = entry;
  return entry;
}

/**
 * Start provisioning as soon as the user is through the access check.
 */
export function beginProvisioning(
  identity: string,
  client: FirstRunClient,
): void {
  if (started?.identity !== identity) begin(identity, client);
}

export const beginFirstRun = beginProvisioning;

export function ensureSession(
  identity: string,
  client: FirstRunClient,
): Promise<string | null> {
  const entry =
    started?.identity === identity ? started : begin(identity, client);
  entry.sessionTaskId ??= entry.provisioned.then((channels) =>
    isFirstRun(channels)
      ? client.startOnboardingSession().catch(() => null)
      : null,
  );
  return entry.sessionTaskId;
}

/**
 * The result of {@link beginProvisioning}, shared rather than consumed: `personal_created` and
 * `general_created` are true only for whoever provisions first, so every reader has to see the
 * same response or the later ones decide this is not a first run.
 */
export function firstRun(identity: string, client: FirstRunClient): FirstRun {
  return started?.identity === identity ? started : begin(identity, client);
}
