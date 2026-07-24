import { afterEach, describe, expect, it, vi } from "vitest";
import {
  formatTimestampInTimezone,
  formatTimezoneAbbreviation,
  formatTimezoneLabel,
  isValidTimezone,
  systemTimezone,
  timezoneOptions,
} from "./timezone";

afterEach(() => vi.restoreAllMocks());

describe("systemTimezone", () => {
  it("returns the runtime IANA timezone", () => {
    vi.spyOn(Intl, "DateTimeFormat").mockReturnValue({
      resolvedOptions: () => ({ timeZone: "America/New_York" }),
    } as Intl.DateTimeFormat);

    expect(systemTimezone()).toBe("America/New_York");
  });

  it("falls back to UTC when timezone detection fails", () => {
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => {
      throw new Error("unavailable");
    });

    expect(systemTimezone()).toBe("UTC");
  });
});

describe("timezone options", () => {
  it("formats a timestamp in the requested timezone", () => {
    const formatted = formatTimestampInTimezone(
      new Date("2026-07-22T16:00:00.000Z"),
      "America/Toronto",
    );

    expect(formatted).toContain("12:00 PM");
  });

  it("formats IANA names with their current UTC offset", () => {
    expect(formatTimezoneLabel("America/Toronto")).toMatch(
      /^America \/ Toronto \(UTC-0[45]:00\)$/,
    );
  });

  it.each([
    ["2026-07-22T12:00:00.000Z", "EDT"],
    ["2026-01-22T12:00:00.000Z", "EST"],
  ])("formats Toronto's abbreviation on %s", (date, expected) => {
    expect(formatTimezoneAbbreviation("America/Toronto", new Date(date))).toBe(
      expected,
    );
  });

  it("includes the detected timezone and UTC", () => {
    vi.spyOn(Intl, "DateTimeFormat").mockReturnValueOnce({
      resolvedOptions: () => ({ timeZone: "America/New_York" }),
    } as Intl.DateTimeFormat);

    expect(timezoneOptions().map(({ value }) => value)).toEqual(
      expect.arrayContaining(["America/New_York", "UTC"]),
    );
  });

  it.each([
    ["Europe/London", true],
    ["America/Toronto", true],
    ["Not/A_Timezone", false],
  ])("validates %s", (timezone, expected) => {
    expect(isValidTimezone(timezone)).toBe(expected);
  });
});
