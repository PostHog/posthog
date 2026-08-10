import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPosthog = {
  init: vi.fn(),
  register: vi.fn(),
  unregister: vi.fn(),
  onFeatureFlags: vi.fn(),
  isFeatureEnabled: vi.fn(),
  startSessionRecording: vi.fn(),
  capture: vi.fn(),
  identify: vi.fn(),
  group: vi.fn(),
  reset: vi.fn(),
  captureException: vi.fn(),
  reloadFeatureFlags: vi.fn(),
};

vi.mock("posthog-js/dist/module.full.no-external", () => ({
  default: mockPosthog,
}));

vi.mock("posthog-js/dist/posthog-recorder", () => ({}));

async function loadAnalytics() {
  vi.resetModules();
  return await import("./posthogAnalyticsImpl");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("VITE_POSTHOG_API_KEY", "test-key");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("onFeatureFlagsLoaded", () => {
  it("delivers pre-init subscribers when init runs", async () => {
    const { initializePostHog, onFeatureFlagsLoaded } = await loadAnalytics();

    const cb = vi.fn();
    onFeatureFlagsLoaded(cb);

    expect(mockPosthog.onFeatureFlags).not.toHaveBeenCalled();

    initializePostHog();

    expect(mockPosthog.onFeatureFlags).toHaveBeenCalledTimes(1);
    expect(mockPosthog.onFeatureFlags).toHaveBeenCalledWith(cb);
  });

  it("does not register a buffered listener that unsubscribed before init", async () => {
    const { initializePostHog, onFeatureFlagsLoaded } = await loadAnalytics();

    const cb = vi.fn();
    const off = onFeatureFlagsLoaded(cb);
    off();

    initializePostHog();

    expect(mockPosthog.onFeatureFlags).not.toHaveBeenCalled();
  });

  it("propagates unsubscribe to PostHog when called after init", async () => {
    const realUnsub = vi.fn();
    mockPosthog.onFeatureFlags.mockReturnValue(realUnsub);

    const { initializePostHog, onFeatureFlagsLoaded } = await loadAnalytics();

    const off = onFeatureFlagsLoaded(vi.fn());
    initializePostHog();
    off();

    expect(realUnsub).toHaveBeenCalledTimes(1);
  });

  it("routes post-init subscribers directly to PostHog", async () => {
    const realUnsub = vi.fn();
    mockPosthog.onFeatureFlags.mockReturnValue(realUnsub);

    const { initializePostHog, onFeatureFlagsLoaded } = await loadAnalytics();
    initializePostHog();

    const cb = vi.fn();
    const off = onFeatureFlagsLoaded(cb);

    expect(mockPosthog.onFeatureFlags).toHaveBeenCalledWith(cb);

    off();
    expect(realUnsub).toHaveBeenCalledTimes(1);
  });
});

describe("registerAppVersion", () => {
  it("registers app_version as a super property after init", async () => {
    const { initializePostHog, registerAppVersion } = await loadAnalytics();

    initializePostHog();
    registerAppVersion("1.2.3");

    expect(mockPosthog.register).toHaveBeenCalledWith({ app_version: "1.2.3" });
  });

  it("does nothing before init", async () => {
    const { registerAppVersion } = await loadAnalytics();

    registerAppVersion("1.2.3");

    expect(mockPosthog.register).not.toHaveBeenCalled();
  });

  it("re-registers app_version after resetUser clears super properties", async () => {
    const { initializePostHog, registerAppVersion, resetUser } =
      await loadAnalytics();

    initializePostHog();
    registerAppVersion("1.2.3");

    resetUser();

    expect(mockPosthog.reset).toHaveBeenCalledTimes(1);
    expect(mockPosthog.register).toHaveBeenLastCalledWith({
      team: "posthog-code",
      app_version: "1.2.3",
    });
  });
});

describe("track", () => {
  it("stamps inbox_client on inbox events", async () => {
    const { initializePostHog, track } = await loadAnalytics();
    initializePostHog();

    track(ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED, {
      source_product: "github",
      is_first_connection: true,
      via_setup_wizard: false,
    });

    expect(mockPosthog.capture).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED,
      expect.objectContaining({ inbox_client: "code" }),
    );
  });

  it("does not stamp inbox_client on non-inbox events", async () => {
    const { initializePostHog, track } = await loadAnalytics();
    initializePostHog();

    track(ANALYTICS_EVENTS.PROMPT_HISTORY_OPENED, { entry_count: 3 });

    expect(mockPosthog.capture).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.PROMPT_HISTORY_OPENED,
      expect.not.objectContaining({ inbox_client: expect.anything() }),
    );
  });

  it("does nothing before init", async () => {
    const { track } = await loadAnalytics();

    track(ANALYTICS_EVENTS.SIGNAL_SOURCE_CONNECTED, {
      source_product: "github",
      is_first_connection: true,
      via_setup_wizard: false,
    });

    expect(mockPosthog.capture).not.toHaveBeenCalled();
  });
});

describe("initializePostHog", () => {
  it("is idempotent across repeat calls", async () => {
    const { initializePostHog } = await loadAnalytics();

    initializePostHog();
    initializePostHog();

    expect(mockPosthog.init).toHaveBeenCalledTimes(1);
  });

  it("does nothing when no API key is set", async () => {
    vi.stubEnv("VITE_POSTHOG_API_KEY", "");
    const { initializePostHog, onFeatureFlagsLoaded } = await loadAnalytics();

    const cb = vi.fn();
    onFeatureFlagsLoaded(cb);
    initializePostHog();

    expect(mockPosthog.init).not.toHaveBeenCalled();
    expect(mockPosthog.onFeatureFlags).not.toHaveBeenCalled();
  });

  it("disables replay canvas capture regardless of remote config", async () => {
    const { initializePostHog } = await loadAnalytics();

    initializePostHog();

    expect(mockPosthog.init).toHaveBeenCalledWith(
      "test-key",
      expect.objectContaining({
        session_recording: { captureCanvas: { recordCanvas: false } },
      }),
    );
  });

  it("bootstraps posthog with the main-owned session id", async () => {
    const { initializePostHog } = await loadAnalytics();

    initializePostHog("0190abcd-1234-7890-8abc-def012345678");

    expect(mockPosthog.init).toHaveBeenCalledWith(
      "test-key",
      expect.objectContaining({
        bootstrap: { sessionID: "0190abcd-1234-7890-8abc-def012345678" },
        session_idle_timeout_seconds: 36_000,
      }),
    );
  });

  it("omits bootstrap when no session id is provided", async () => {
    const { initializePostHog } = await loadAnalytics();

    initializePostHog();

    expect(mockPosthog.init).toHaveBeenCalledWith(
      "test-key",
      expect.not.objectContaining({ bootstrap: expect.anything() }),
    );
  });
});
