import { setRootContainer } from "@posthog/di/container";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ANALYTICS_TRACKER, track } from "@posthog/ui/shell/analytics";
import {
  initializePostHog,
  posthogAnalyticsTracker,
  registerCodexSubscription,
} from "@posthog/ui/shell/posthogAnalyticsImpl";
import posthog from "posthog-js/dist/module.full.no-external";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type EnqueuedRequest = {
  method: string;
  url: string;
  data: { event: string; properties: Record<string, unknown> };
};

function tapRequestQueue(): { enqueued: EnqueuedRequest[] } {
  const enqueued: EnqueuedRequest[] = [];
  const queue = (
    posthog as unknown as {
      _requestQueue: { enqueue: (r: EnqueuedRequest) => void };
    }
  )._requestQueue;
  const realEnqueue = queue.enqueue.bind(queue);
  queue.enqueue = (request: EnqueuedRequest) => {
    enqueued.push(JSON.parse(JSON.stringify(request)) as EnqueuedRequest);
    return realEnqueue(request);
  };
  return { enqueued };
}

function captureEventsOnWire(
  enqueued: EnqueuedRequest[],
): EnqueuedRequest["data"][] {
  return enqueued
    .filter((r) => r.method === "POST" && r.url.endsWith("/e/"))
    .map((r) => r.data);
}

describe("subscription analytics evidence", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_POSTHOG_API_KEY", "phc_test_key");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("1", { status: 200 })),
    );
    (window as unknown as { fetch: unknown }).fetch = globalThis.fetch;

    initializePostHog();
    posthog.sessionRecording?.stopRecording();

    setRootContainer({
      get: (id: unknown) => {
        if (id === ANALYTICS_TRACKER) return posthogAnalyticsTracker;
        throw new Error(`unbound ${String(id)}`);
      },
      getAll: () => [],
      isBound: (id: unknown) => id === ANALYTICS_TRACKER,
      bind: () => {
        throw new Error("not needed");
      },
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("registers the subscription state as SDK super properties", () => {
    registerCodexSubscription({ access: "own-subscription", connected: true });

    expect(posthog.get_property("codex_model_access" as never)).toBe(
      "own-subscription",
    );
    expect(posthog.get_property("codex_subscription_connected" as never)).toBe(
      true,
    );
  });

  it("sends a session's run event with the subscription state attached", async () => {
    const { enqueued } = tapRequestQueue();
    registerCodexSubscription({ access: "own-subscription", connected: true });

    track(ANALYTICS_EVENTS.TASK_RUN, {
      task_id: "task-evidence-1",
      execution_type: "local",
    });
    await Promise.resolve();

    const events = captureEventsOnWire(enqueued);
    const runEvents = events.filter(
      (e) => e.event === ANALYTICS_EVENTS.TASK_RUN,
    );
    expect(runEvents).toHaveLength(1);
    expect(runEvents[0]?.properties.codex_model_access).toBe(
      "own-subscription",
    );
    expect(runEvents[0]?.properties.codex_subscription_connected).toBe(true);
    expect(runEvents[0]?.properties.task_id).toBe("task-evidence-1");
  });

  it("gateway runs are tracked too, with their own billing value", async () => {
    const { enqueued } = tapRequestQueue();
    registerCodexSubscription({
      access: "posthog-gateway",
      connected: false,
    });

    track(ANALYTICS_EVENTS.TASK_RUN, {
      task_id: "task-evidence-gw",
      execution_type: "local",
    });
    await Promise.resolve();

    const events = captureEventsOnWire(enqueued);
    const runEvents = events.filter(
      (e) => e.event === ANALYTICS_EVENTS.TASK_RUN,
    );
    expect(runEvents).toHaveLength(1);
    expect(runEvents[0]?.properties.codex_model_access).toBe("posthog-gateway");
  });
});
