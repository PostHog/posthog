import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CSP_VIOLATION_NOTIFICATION,
  startCspViolationCollector,
} from "./cspViolationCollector";

function violation(blockedURL: string, effectiveDirective = "style-src-elem") {
  return {
    jsonrpc: "2.0",
    method: CSP_VIOLATION_NOTIFICATION,
    params: {
      report: {
        type: "csp-violation",
        url: "about",
        body: { documentURL: "about", blockedURL, effectiveDirective },
      },
    },
  };
}

function post(data: unknown) {
  window.dispatchEvent(new MessageEvent("message", { data }));
}

let dispose: (() => void) | null = null;

afterEach(() => {
  dispose?.();
  dispose = null;
});

describe("startCspViolationCollector", () => {
  it("sends each distinct violation once", () => {
    const send = vi.fn();
    dispose = startCspViolationCollector(send);

    post(violation("https://mcp.us.posthog.com/styles.css"));
    post(violation("https://mcp.us.posthog.com/styles.css"));
    post(violation("https://mcp.us.posthog.com/main.js", "script-src-elem"));

    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[0][0].body.blockedURL).toBe(
      "https://mcp.us.posthog.com/styles.css",
    );
  });

  it("stops sending once the distinct-report cap is reached", () => {
    const send = vi.fn();
    dispose = startCspViolationCollector(send, 2);

    post(violation("https://mcp.us.posthog.com/1.css"));
    post(violation("https://mcp.us.posthog.com/2.css"));
    post(violation("https://mcp.us.posthog.com/3.css"));

    expect(send).toHaveBeenCalledTimes(2);
  });

  it.each([
    [
      "an MCP bridge message",
      { method: "ui/notifications/sandbox-proxy-ready" },
    ],
    ["a missing report", { method: CSP_VIOLATION_NOTIFICATION, params: {} }],
    [
      "a report of another type",
      {
        method: CSP_VIOLATION_NOTIFICATION,
        params: { report: { type: "deprecation", body: {} } },
      },
    ],
    ["a non-object payload", "hello"],
  ])("ignores %s", (_name, data) => {
    const send = vi.fn();
    dispose = startCspViolationCollector(send);

    post(data);

    expect(send).not.toHaveBeenCalled();
  });

  it("stops listening after disposal", () => {
    const send = vi.fn();
    startCspViolationCollector(send)();

    post(violation("https://mcp.us.posthog.com/a.css"));

    expect(send).not.toHaveBeenCalled();
  });
});
