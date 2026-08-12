import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  formatSlaCountdown,
  formatTicketAge,
  ticketAssigneeName,
  ticketPriorityLabel,
  ticketRequesterName,
} from "./ticketPresentation";

const NOW = Date.parse("2026-08-12T12:00:00Z");

function ticket(overrides: Partial<SupportTicket> = {}): SupportTicket {
  return {
    person: null,
    anonymous_traits: null,
    email_from: null,
    assignee: null,
    priority: "medium",
    ...overrides,
  } as SupportTicket;
}

function isoAfter(offsetMs: number): string {
  return new Date(NOW + offsetMs).toISOString();
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
      "an inbound email address",
      { email_from: "sam@example.com" },
      "sam@example.com",
    ],
    ["nothing at all", {}, "Unknown requester"],
  ])("names the requester from %s", (_case, overrides, expected) => {
    expect(ticketRequesterName(ticket(overrides))).toBe(expected);
  });

  const assignedToUser = (
    user: Record<string, string>,
  ): SupportTicket["assignee"] => ({
    id: "00000000-0000-0000-0000-000000000001",
    type: "user",
    user,
    role: null,
  });

  const assignedToRole = (
    role: Record<string, string>,
  ): SupportTicket["assignee"] => ({
    id: "00000000-0000-0000-0000-000000000002",
    type: "role",
    user: null,
    role,
  });

  it.each<[string, SupportTicket["assignee"], string]>([
    ["no assignment", null, "Unassigned"],
    ["a user with a name", assignedToUser({ first_name: "Kim" }), "Kim"],
    [
      "a user with only an email",
      assignedToUser({ email: "kim@example.com" }),
      "kim@example.com",
    ],
    [
      "a role, which is an unclaimed pool",
      assignedToRole({ name: "Support" }),
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
    ["under a minute", -30_000, "now"],
    ["minutes", -12 * 60_000, "12m"],
    ["hours", -3 * 60 * 60_000, "3h"],
    ["days", -2 * 24 * 60 * 60_000, "2d"],
  ])("formats an age of %s", (_case, offsetMs, expected) => {
    expect(formatTicketAge(isoAfter(offsetMs), NOW)).toBe(expected);
  });

  it.each<[string, string | null, string]>([
    ["no deadline", null, ""],
    ["an unparseable deadline", "sometime", ""],
  ])("returns nothing for %s", (_case, value, expected) => {
    expect(formatTicketAge(value, NOW)).toBe(expected);
  });

  it.each<[string, number, string]>([
    ["time remaining in minutes", 30 * 60_000, "SLA in 30m"],
    ["time remaining in hours", 3 * 60 * 60_000, "SLA in 3h"],
    ["a missed deadline", -2 * 60 * 60_000, "SLA 2h overdue"],
  ])("counts down with %s", (_case, offsetMs, expected) => {
    expect(formatSlaCountdown(isoAfter(offsetMs), NOW)).toBe(expected);
  });

  it("has no countdown without a deadline", () => {
    expect(formatSlaCountdown(null, NOW)).toBeNull();
  });
});
