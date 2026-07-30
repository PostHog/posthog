import posthog from "posthog-js/dist/module.full.no-external";
// Import the recorder to set up __PosthogExtensions__.initSessionRecording
// The module.full.no-external bundle includes rrweb but not the initSessionRecording function
// posthog-recorder (vs lazy-recorder) ensures recording is ready immediately
import "posthog-js/dist/posthog-recorder";
import type {
  AnalyticsProperties,
  IAnalytics,
} from "@posthog/platform/analytics";
import {
  type EventPropertyMap,
  isInboxAnalyticsEvent,
  type UserIdentifyProperties,
} from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import type { FeatureFlags } from "@posthog/ui/features/feature-flags/identifiers";
import type { PermissionRequest } from "@posthog/ui/features/sessions/sessionLogTypes";
import type {
  AnalyticsTracker,
  AnalyticsUserGroups,
} from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";

const log = logger.scope("analytics");

// Client discriminator stamped on every inbox analytics event so the shared
// PostHog project can be sliced by surface (this desktop host = "code";
// mobile sends "mobile"; the PostHog web frontend sends "cloud"). Mirrors
// posthog's frontend/src/scenes/inbox/inboxAnalytics.ts.
const INBOX_CLIENT = "code" as const;

let isInitialized = false;

// Cached so it can be re-applied after posthog.reset() clears super properties.
let registeredAppVersion: string | null = null;

// posthog.reset() wipes super properties, so these are re-registered after each reset.
function registerPersistentSuperProperties() {
  posthog.register({
    team: "posthog-code",
    ...(registeredAppVersion !== null
      ? { app_version: registeredAppVersion }
      : {}),
  });
}

type PendingFlagListener = {
  callback: () => void;
  unsubscribe: (() => void) | null;
};

// Subscribers added before initializePostHog runs.
const pendingFlagListeners = new Set<PendingFlagListener>();

const SESSION_IDLE_TIMEOUT_SECONDS = 36_000;

export function initializePostHog(sessionId?: string) {
  const apiKey = import.meta.env.VITE_POSTHOG_API_KEY;
  const apiHost =
    import.meta.env.VITE_POSTHOG_API_HOST || "https://internal-c.posthog.com";
  const uiHost =
    import.meta.env.VITE_POSTHOG_UI_HOST || "https://us.i.posthog.com";

  if (!apiKey || isInitialized) {
    return;
  }

  posthog.init(apiKey, {
    defaults: "2026-05-30",
    api_host: apiHost,
    ui_host: uiHost,
    // The epoch turns capture_pageview into "history_change". This app routes via
    // createHashHistory() (packages/ui/src/router/router.ts), so the route lives in
    // the URL hash and $pathname is identical for every screen — automatic pageviews
    // would collapse all routes into one and corrupt route-level analytics. Opt out
    // and rely on explicit instrumentation instead.
    capture_pageview: false,
    disable_session_recording: false,
    // Never let the project's remote canvasRecording config apply here: our
    // canvases are xterm terminals (secrets show up as pixels, bypassing text
    // masking) and decorative WebGL (hedgehog, confetti). Capturing them costs
    // an image encode per canvas at canvasFps for the whole app lifetime.
    session_recording: {
      captureCanvas: { recordCanvas: false },
    },
    // The shared analytics project runs many popover surveys aimed at the
    // PostHog web app; any one without URL/event conditions would render here
    // too. This app only submits survey responses through its own UI
    // (captureSurveyResponse), which posthog-js survey rendering being off
    // does not affect.
    disable_surveys: true,
    session_idle_timeout_seconds: SESSION_IDLE_TIMEOUT_SECONDS,
    ...(sessionId ? { bootstrap: { sessionID: sessionId } } : {}),
    capture_exceptions: import.meta.env.DEV
      ? false
      : {
          capture_unhandled_errors: true,
          capture_unhandled_rejections: true,
          capture_console_errors: true,
        },
    loaded: () => {
      posthog.startSessionRecording();
    },
  });

  // Clear stale task-scoped super-properties from the previous session.
  posthog.unregister("signal_report_id");

  isInitialized = true;

  // Dev-only: expose the posthog instance so flags can be toggled from the
  // renderer console, e.g. `posthog.featureFlags.override({ "agent-platform": true })`
  // (and `posthog.featureFlags.override(false)` to clear). The module build
  // doesn't attach to window otherwise.
  if (import.meta.env.DEV) {
    (window as unknown as { posthog?: typeof posthog }).posthog = posthog;
  }

  registerPersistentSuperProperties();

  for (const listener of pendingFlagListeners) {
    listener.unsubscribe = posthog.onFeatureFlags(listener.callback);
  }
  pendingFlagListeners.clear();
}

/**
 * Log the current session recording status for debugging
 */
export function logSessionRecordingStatus() {
  if (!isInitialized) {
    log.warn("PostHog not initialized");
    return;
  }

  const sessionRecording = posthog.sessionRecording;
  const remoteConfig = posthog.get_property("$session_recording_remote_config");

  log.info("Session Recording Debug:", {
    started: sessionRecording?.started,
    status: sessionRecording?.status,
    remoteConfigEnabled: remoteConfig?.enabled,
    remoteConfig,
    windowLocationHref: window.location?.href,
    configDisableSessionRecording: posthog.config?.disable_session_recording,
  });
}

/**
 * Manually start session recording.
 * Use this to force start recording regardless of triggers.
 */
export function startSessionRecording() {
  if (!isInitialized) {
    return;
  }

  log.info("Attempting to start session recording...");

  // Use PostHog's startSessionRecording API which overrides triggers
  posthog.startSessionRecording();

  // Log status after attempting to start
  setTimeout(() => {
    log.info("Session recording status after manual start:");
    logSessionRecordingStatus();
  }, 1000);
}

// Register the app version as a super property so it rides along on every event.
export function registerAppVersion(appVersion: string) {
  registeredAppVersion = appVersion;

  if (!isInitialized) {
    return;
  }

  posthog.register({ app_version: appVersion });
}

export function identifyUser(
  userId: string,
  properties?: UserIdentifyProperties,
) {
  if (!isInitialized) {
    return;
  }

  posthog.identify(userId, properties);
}

export function setUserGroups(user: AnalyticsUserGroups) {
  if (!isInitialized) {
    return;
  }

  if (user.team) {
    posthog.group("project", user.team.uuid, {
      id: user.team.id,
      uuid: user.team.uuid,
      name: user.team.name,
    });
  }

  if (user.organization) {
    posthog.group("organization", user.organization.id, {
      id: user.organization.id,
      name: user.organization.name,
      slug: user.organization.slug,
    });
  }
}

export function resetUser() {
  if (!isInitialized) {
    return;
  }

  posthog.reset();

  // reset() clears super properties; re-apply the persistent ones.
  registerPersistentSuperProperties();
}

/**
 * Attach (or clear) task-scoped super-properties so every subsequent event
 * carries the context of the currently active task. Pass `null` when no task
 * is active (e.g. when navigating to a non-task view) to clear the context.
 *
 * Currently used to tag every event fired while the user is inside a task
 * launched from an inbox report via the Discuss button.
 */
export function setActiveTaskAnalyticsContext(task: Task | null) {
  if (!isInitialized) {
    return;
  }

  if (task?.signal_report) {
    posthog.register({ signal_report_id: task.signal_report });
  } else {
    posthog.unregister("signal_report_id");
  }
}

export function track<K extends keyof EventPropertyMap>(
  eventName: K,
  ...args: EventPropertyMap[K] extends never
    ? []
    : EventPropertyMap[K] extends undefined
      ? [properties?: EventPropertyMap[K]]
      : [properties: EventPropertyMap[K]]
) {
  if (!isInitialized) {
    return;
  }

  // Stamp inbox events with the client discriminator. Spread first so a caller
  // could override it, matching posthog's inboxAnalytics.ts (none do today).
  const properties = isInboxAnalyticsEvent(eventName)
    ? { inbox_client: INBOX_CLIENT, ...args[0] }
    : args[0];

  posthog.capture(eventName, properties);
}

/**
 * Record a survey response via posthog-js's `survey sent` event. Pass one entry
 * per answered question; they're submitted together as a single response. The
 * survey must already exist (and be launched) in the project the app reports to,
 * or the response will not attach to it.
 */
export function captureSurveyResponse({
  surveyId,
  responses,
}: {
  surveyId: string;
  responses: Array<{ questionId: string; response: string }>;
}) {
  if (!isInitialized) {
    return;
  }

  const properties: Record<string, unknown> = {
    $survey_id: surveyId,
    $survey_questions: responses.map(({ questionId }) => ({ id: questionId })),
  };
  // Newer ingestion keys each response by question id.
  for (const { questionId, response } of responses) {
    properties[`$survey_response_${questionId}`] = response;
  }
  // `$survey_response` is the legacy single-question key; only set it when there
  // is exactly one answer, otherwise it would be ambiguous.
  if (responses.length === 1) {
    properties.$survey_response = responses[0].response;
  }

  posthog.capture("survey sent", properties);
}

/**
 * Build tool metadata for analytics on permission requests
 */
export function buildPermissionToolMetadata(
  permission?: PermissionRequest,
  selectedOptionId?: string,
  customInput?: string,
): Record<string, unknown> {
  const selectedOption = permission?.options?.find(
    (o) => o.optionId === selectedOptionId,
  );
  const rawInput = permission?.toolCall?.rawInput as
    | Record<string, unknown>
    | undefined;

  return {
    tool_name: rawInput?.toolName,
    option_id: selectedOptionId,
    option_kind: selectedOption?.kind ?? "unknown",
    custom_input: customInput,
  };
}

/**
 * Capture an exception for error tracking using PostHog's built-in exception tracking.
 */
export function captureException(
  error: Error,
  additionalProperties?: Record<string, unknown>,
) {
  if (!isInitialized) {
    return;
  }

  posthog.captureException(error, {
    team: "posthog-code",
    ...additionalProperties,
  });
}

// ============================================================================
// Feature Flags
// ============================================================================

/**
 * Check if a feature flag is enabled for the current user.
 * Returns false if PostHog is not initialized or flag is not found.
 */
export function isFeatureFlagEnabled(flagKey: string): boolean {
  if (!isInitialized) {
    return false;
  }

  return posthog.isFeatureEnabled(flagKey) ?? false;
}

/**
 * Subscribe to feature flag changes.
 * Callback is called when flags are loaded or updated.
 * Returns unsubscribe function.
 */
export function onFeatureFlagsLoaded(callback: () => void): () => void {
  if (isInitialized) {
    return posthog.onFeatureFlags(callback);
  }

  const listener: PendingFlagListener = { callback, unsubscribe: null };
  pendingFlagListeners.add(listener);
  return () => {
    if (listener.unsubscribe) {
      listener.unsubscribe();
    } else {
      pendingFlagListeners.delete(listener);
    }
  };
}

/**
 * Reload feature flags from the server.
 * Useful after a person property change (e.g., invite code redemption).
 */
export function reloadFeatureFlags(): void {
  if (!isInitialized) {
    return;
  }

  posthog.reloadFeatureFlags();
}

/**
 * posthog-js implementation of the ANALYTICS_TRACKER port. Bound by the host
 * composition root so packages/ui stays free of any direct posthog access.
 */
export const posthogAnalyticsTracker: AnalyticsTracker = {
  track,
  setActiveTaskContext: setActiveTaskAnalyticsContext,
  captureException,
  identifyUser,
  setUserGroups,
  resetUser,
  captureSurveyResponse,
};

/**
 * posthog-js implementation of the FEATURE_FLAGS port.
 */
export const posthogFeatureFlags: FeatureFlags = {
  isEnabled: isFeatureFlagEnabled,
  onFlagsLoaded: onFeatureFlagsLoaded,
};

// ============================================================================
// Platform ANALYTICS_SERVICE (IAnalytics)
// ============================================================================

let analyticsCurrentUserId: string | null = null;
let analyticsSessionId: string | null = null;

/**
 * posthog-js implementation of the platform ANALYTICS_SERVICE port. Desktop
 * backs this with posthog-node in the Electron main process; the web host has
 * no Node process, so it binds this so its core services (e.g. cloud-task)
 * report through the SAME posthog-js instance the UI tracker and feature-flag
 * ports use. Every method no-ops safely until initializePostHog has run with a
 * real project key.
 */
export const posthogAnalyticsService: IAnalytics = {
  initialize: () => initializePostHog(),
  track: (eventName: string, properties?: AnalyticsProperties) => {
    if (!isInitialized) return;
    posthog.capture(eventName, properties);
  },
  identify: (userId: string, properties?: AnalyticsProperties) => {
    analyticsCurrentUserId = userId;
    if (!isInitialized) return;
    posthog.identify(userId, properties);
  },
  setCurrentUserId: (userId: string | null) => {
    analyticsCurrentUserId = userId;
  },
  getCurrentUserId: () => analyticsCurrentUserId,
  getOrCreateSessionId: () => {
    if (!analyticsSessionId) analyticsSessionId = crypto.randomUUID();
    return analyticsSessionId;
  },
  resetUser: () => {
    analyticsCurrentUserId = null;
    resetUser();
  },
  captureException: (error: unknown, additionalProperties?) =>
    captureException(
      error instanceof Error ? error : new Error(String(error)),
      additionalProperties,
    ),
  flush: () => Promise.resolve(),
  shutdown: () => Promise.resolve(),
};
