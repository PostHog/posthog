import { REPORT_MODEL_RESOLVER } from "@posthog/core/inbox/identifiers";
import {
  SPEECH_SETTINGS_PROVIDER,
  SPEECH_USER_NAME_PROVIDER,
} from "@posthog/core/speech/identifiers";
import type { HostCapabilityRequirement } from "@posthog/di/hostCapabilities";
import { HOST_CAPABILITIES } from "@posthog/platform/host-capabilities";
import { SPEECH_SERVICE } from "@posthog/platform/speech";
import { AUTH_SIDE_EFFECTS } from "@posthog/ui/features/auth/identifiers";
import { REVIEW_HOST } from "@posthog/ui/features/code-review/reviewHost";
import { CONNECTIVITY_CLIENT } from "@posthog/ui/features/connectivity/connectivityClient";
import { FEATURE_FLAGS } from "@posthog/ui/features/feature-flags/identifiers";
import { GIT_CACHE_KEY_PROVIDER } from "@posthog/ui/features/git-interaction/gitCacheProvider";
import { SPEECH_NOTIFY_SETTINGS } from "@posthog/ui/features/notifications/identifiers";
import { UPDATES_CLIENT } from "@posthog/ui/features/updates/updatesClient";
import { DIFF_WORKER_FACTORY } from "@posthog/ui/shell/diffWorkerHost";

/**
 * Host capabilities every host mounting the shared app must bind.
 *
 * The contract: shared `@posthog/ui` / `@posthog/core` resolve these tokens via
 * `useService` / `resolveService`, so any host that renders the shared UI has to
 * provide an implementation. Unlike a `TypedContainer<HostBindings>` (which only
 * type-checks the provider side) or a tRPC procedure stub (which may legitimately
 * `NOT_FOUND` at call time), a missing binding here is always a bug — it just
 * hides until a user reaches the resolving code path.
 *
 * Each host passes this list to `assertHostCapabilities` at the end of its
 * composition root (see `apps/web/src/web-container.ts` and the desktop renderer
 * container) so a gap fails at startup rather than at the first navigation that
 * needs it — which the web e2e boot test (`apps/web/tests/e2e`) turns into a CI
 * gate: an unbound capability throws at container load, the app never mounts,
 * and the boot spec fails. Add an entry whenever shared code starts resolving a
 * new host-provided token via service location.
 *
 * Excluded on purpose: core-module services (they fail at module load, a
 * different and already-loud failure mode) and host-specific/local-only
 * capabilities (e.g. file watchers, local handoff) that not every host provides.
 */
export const REQUIRED_HOST_CAPABILITIES: readonly HostCapabilityRequirement[] =
  [
    {
      token: HOST_CAPABILITIES,
      description: "coarse host capability flags the shared UI branches on",
    },
    {
      token: FEATURE_FLAGS,
      description: "feature-flag gating across the app",
    },
    {
      token: AUTH_SIDE_EFFECTS,
      description: "auth lifecycle side effects (login/logout/session)",
    },
    {
      token: CONNECTIVITY_CLIENT,
      description: "online/offline status the UI reacts to",
    },
    {
      token: UPDATES_CLIENT,
      description: "app-update status surfaced in settings",
    },
    {
      token: GIT_CACHE_KEY_PROVIDER,
      description: "git query cache keys",
    },
    {
      token: REVIEW_HOST,
      description: "code-review page host wiring",
    },
    {
      token: DIFF_WORKER_FACTORY,
      description: "diff computation worker for review/diffs",
    },
    {
      token: REPORT_MODEL_RESOLVER,
      description: "default cloud-run model resolution (canvas/home/inbox)",
    },
    {
      token: SPEECH_SERVICE,
      description: "text-to-speech playback for agent narration",
    },
    {
      token: SPEECH_SETTINGS_PROVIDER,
      description: "spoken-narration enablement and voice",
    },
    {
      token: SPEECH_USER_NAME_PROVIDER,
      description: "signed-in user's first name for spoken greetings",
    },
    {
      token: SPEECH_NOTIFY_SETTINGS,
      description: "per-kind gating for spoken notifications",
    },
  ];
