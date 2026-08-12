import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPosthog = {
  init: vi.fn(),
  config: {
    api_host: "https://internal-c.posthog.com",
    token: "test-key",
  } as Record<string, string>,
  get_distinct_id: vi.fn(() => "distinct-1"),
  get_session_id: vi.fn(() => "session-1"),
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
  vi.unstubAllGlobals();
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

describe("buildCspReportUrl", () => {
  it("targets /report/ on the ingestion host with the session's ids", async () => {
    const { buildCspReportUrl } = await loadAnalytics();

    const url = buildCspReportUrl({
      apiHost: "https://internal-c.posthog.com",
      token: "phc_test",
      distinctId: "distinct-1",
      sessionId: "session-1",
    });

    expect(url).toBe(
      "https://internal-c.posthog.com/report/?token=phc_test&v=2&distinct_id=distinct-1&session_id=session-1",
    );
  });

  it.each([
    ["no host", { token: "phc_test" }],
    ["no token", { apiHost: "https://internal-c.posthog.com" }],
  ])("returns null with %s to report to", async (_name, params) => {
    const { buildCspReportUrl } = await loadAnalytics();

    expect(buildCspReportUrl(params)).toBeNull();
  });
});

describe("reportCspViolation", () => {
  const report = {
    type: "csp-violation" as const,
    url: "mcp-sandbox://proxy/",
    body: { blockedURL: "https://mcp.us.posthog.com/a.css" },
  };

  it("posts the report as a Reporting API bundle", async () => {
    const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
      Promise.resolve(new Response(null, { status: 204 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { initializePostHog, reportCspViolation } = await loadAnalytics();
    initializePostHog();

    reportCspViolation(report);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/report/?token=test-key&v=2");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({
      "Content-Type": "application/reports+json",
    });
    expect(JSON.parse(init.body as string)).toEqual([report]);
  });

  it("sends no request before posthog has a project to report to", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { reportCspViolation } = await loadAnalytics();

    reportCspViolation(report);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
