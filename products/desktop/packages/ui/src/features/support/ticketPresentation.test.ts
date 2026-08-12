import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  formatSlaCountdown,
  ticketAssigneeName,
  ticketPriorityLabel,
  ticketRequesterName,
} from "./ticketPresentation";

const NOW = Date.parse("2026-08-12T12:00:00Z");

function ticket(overrides: Partial<SupportTicket> = {}): SupportTicket {
  return { person: null, assignee: null, ...overrides } as SupportTicket;
}

describe("ticket presentation", () => {
  it.each<[string, Partial<SupportTicket>, string]>([
    [
      "an identified person",
      { person: { name: "Priya Raman" } as SupportTicket["person"] },
      "Priya Raman",
    ],
    [
      "a name supplied by the channel",
      { anonymous_traits: { name: "Marco Silva" } },
      "Marco Silva",
    ],
    [
      "only an email trait",
      { anonymous_traits: { email: "dana@example.com" } },
      "dana@example.com",
    ],
    [
      "an inbound address",
      { email_from: "sam@example.com" },
      "sam@example.com",
    ],
    ["nothing at all", {}, "Unknown requester"],
  ])("names the requester from %s", (_case, overrides, expected) => {
    expect(ticketRequesterName(ticket(overrides))).toBe(expected);
  });

  it.each<[string, SupportTicket["assignee"], string]>([
    ["no assignment", null, "Unassigned"],
    [
      "a user",
      {
        id: "1",
        type: "user",
        user: { email: "kim@example.com" },
        role: null,
      },
      "kim@example.com",
    ],
    [
      "a role, which is an unclaimed pool",
      {
        id: "2",
        type: "role",
        user: null,
        role: { name: "Support" },
      },
      "Support (pool)",
    ],
  ])("names the assignee for %s", (_case, assignee, expected) => {
    expect(ticketAssigneeName(ticket({ assignee }))).toBe(expected);
  });

  it("renders an unset priority as untriaged rather than low", () => {
    expect(ticketPriorityLabel(null)).toBe("No priority");
    expect(ticketPriorityLabel("low")).toBe("Low");
  });

  it.each<[string, number, string]>([
    ["time left in minutes", 30 * 60_000, "SLA in 30m"],
    ["time left in hours", 3 * 60 * 60_000, "SLA in 3h"],
    ["a missed deadline", -2 * 60 * 60_000, "SLA 2h overdue"],
  ])("counts down with %s", (_case, offsetMs, expected) => {
    expect(
      formatSlaCountdown(new Date(NOW + offsetMs).toISOString(), NOW),
    ).toBe(expected);
  });

  it("has no countdown without a deadline", () => {
    expect(formatSlaCountdown(null, NOW)).toBeNull();
  });
});
