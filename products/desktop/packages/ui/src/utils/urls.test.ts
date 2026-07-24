import { getBillingUrl, getPostHogUrl } from "@posthog/ui/utils/urls";
import { describe, expect, it } from "vitest";

describe("getPostHogUrl", () => {
  it("returns null when no region is available and the input is a path", () => {
    expect(getPostHogUrl("/foo")).toBeNull();
  });

  it.each([
    ["us", "/foo", "https://us.posthog.com/foo"],
    ["us", "foo", "https://us.posthog.com/foo"],
    ["eu", "/foo", "https://eu.posthog.com/foo"],
  ] as const)(
    "joins base and path for %s region (path=%s)",
    (region, path, expected) => {
      expect(getPostHogUrl(path, region)).toBe(expected);
    },
  );

  it.each([
    "https://app.posthog.com/organization/billing",
    "http://localhost:8000/checkout",
    "HTTPS://us.posthog.com/foo",
  ])("passes absolute URLs through unchanged: %s", (url) => {
    expect(getPostHogUrl(url, "us")).toBe(url);
  });
});

describe("getBillingUrl", () => {
  it.each([
    [
      "us",
      "https://us.posthog.com/organization/billing/overview?products=posthog_code_usage",
    ],
    [
      "eu",
      "https://eu.posthog.com/organization/billing/overview?products=posthog_code_usage",
    ],
  ] as const)(
    "points at /organization/billing/overview?products=posthog_code_usage on %s",
    (region, expected) => {
      expect(getBillingUrl(region)).toBe(expected);
    },
  );

  it("returns null when no region is available", () => {
    expect(getBillingUrl()).toBeNull();
  });

  it("does not produce the malformed double-scheme URL we used to ship", () => {
    const url = getBillingUrl("us");
    expect(url).not.toMatch(/https?:\/\/[^/]+\/https?:/);
    expect(url).not.toContain("/project/");
  });
});
