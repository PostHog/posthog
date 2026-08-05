import type { Ticket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  assigneeDisplay,
  channelLabel,
  hasPriority,
  priorityLabel,
  requesterLabel,
  slaState,
  snoozePresets,
  statusLabel,
  ticketPreview,
} from "./ticketPresentation";

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: "t-1",
    ticket_number: 42,
    channel_source: "email",
    channel_detail: null,
    distinct_id: "d-1",
    assignee: { id: null, type: "", user: null, role: null },
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
    message_count: 1,
    last_message_at: "2026-07-02T00:00:00Z",
    last_message_text: "Something is broken",
    unread_team_count: 0,
    unread_customer_count: 0,
    session_id: null,
    session_context: null,
    sla_due_at: null,
    snoozed_until: null,
    slack_channel_id: null,
    slack_thread_ts: null,
    slack_team_id: null,
    email_subject: null,
    email_from: null,
    email_to: null,
    cc_participants: null,
    person: null,
    ...overrides,
  } as Ticket;
}

describe("statusLabel", () => {
  it.each([
    ["new", "New"],
    ["open", "Open"],
    ["pending", "Pending"],
    ["on_hold", "On hold"],
    ["resolved", "Resolved"],
    [undefined, "New"],
  ] as const)("labels %s as %s", (status, expected) => {
    expect(statusLabel(status)).toBe(expected);
  });
});

describe("priorityLabel", () => {
  it.each([
    ["low", "Low"],
    ["medium", "Medium"],
    ["high", "High"],
  ] as const)("labels %s as %s", (priority, expected) => {
    expect(priorityLabel(priority)).toBe(expected);
  });

  // Null priority means untriaged — its own state, never "Low".
  it.each([[null], [undefined], [""]] as const)(
    "renders unset priority (%s) as No priority",
    (priority) => {
      expect(priorityLabel(priority as Ticket["priority"])).toBe("No priority");
      expect(hasPriority(priority as Ticket["priority"])).toBe(false);
    },
  );
});

describe("assigneeDisplay", () => {
  it("prefers the user's first name", () => {
    expect(
      assigneeDisplay({
        id: "a",
        type: "user",
        user: { first_name: "Ada", email: "ada@example.com" },
        role: null,
      }),
    ).toEqual({ kind: "user", label: "Ada" });
  });

  it("falls back to the user's email", () => {
    expect(
      assigneeDisplay({
        id: "a",
        type: "user",
        user: { email: "ada@example.com" },
        role: null,
      }),
    ).toEqual({ kind: "user", label: "ada@example.com" });
  });

  it("marks role assignments as a role, not a person", () => {
    expect(
      assigneeDisplay({
        id: "a",
        type: "role",
        user: null,
        role: { name: "Support engineers" },
      }),
    ).toEqual({ kind: "role", label: "Support engineers" });
  });

  it.each([[null], [undefined]])("handles missing assignment (%s)", (value) => {
    expect(assigneeDisplay(value)).toEqual({
      kind: "unassigned",
      label: "Unassigned",
    });
  });
});

describe("channelLabel", () => {
  it.each([
    ["email", "Email"],
    ["slack", "Slack"],
    ["teams", "Teams"],
    ["widget", "Widget"],
  ] as const)("labels %s as %s", (source, expected) => {
    expect(channelLabel(source)).toBe(expected);
  });
});

describe("slaState", () => {
  const now = new Date("2026-07-15T12:00:00Z");

  it("is none without a due date", () => {
    expect(slaState(null, now)).toEqual({ kind: "none" });
    expect(slaState(undefined, now)).toEqual({ kind: "none" });
  });

  it("is due when the deadline is ahead", () => {
    const state = slaState("2026-07-15T13:00:00Z", now);
    expect(state.kind).toBe("due");
  });

  it("is breached when the deadline has passed", () => {
    const state = slaState("2026-07-15T11:00:00Z", now);
    expect(state.kind).toBe("breached");
  });

  it("treats an exactly-due deadline as due, not breached", () => {
    expect(slaState(now.toISOString(), now).kind).toBe("due");
  });

  it("is none for an unparseable date", () => {
    expect(slaState("not-a-date", now)).toEqual({ kind: "none" });
  });
});

describe("requesterLabel", () => {
  it("prefers the identified person", () => {
    const ticket = makeTicket({
      person: {
        id: "p",
        name: "Grace",
        distinct_ids: [],
        properties: {},
        created_at: "",
        is_identified: true,
      },
      anonymous_traits: { name: "Anon" },
      email_from: "grace@example.com",
    });
    expect(requesterLabel(ticket)).toBe("Grace");
  });

  it("falls back to widget traits, then email envelope, then number", () => {
    expect(
      requesterLabel(makeTicket({ anonymous_traits: { name: "Anon" } })),
    ).toBe("Anon");
    expect(
      requesterLabel(
        makeTicket({ anonymous_traits: { email: "anon@example.com" } }),
      ),
    ).toBe("anon@example.com");
    expect(requesterLabel(makeTicket({ email_from: "a@b.com" }))).toBe(
      "a@b.com",
    );
    expect(requesterLabel(makeTicket())).toBe("Ticket #42");
  });
});

describe("ticketPreview", () => {
  it("prefers the email subject over the last message", () => {
    expect(
      ticketPreview(makeTicket({ email_subject: "Billing question" })),
    ).toBe("Billing question");
    expect(ticketPreview(makeTicket())).toBe("Something is broken");
    expect(ticketPreview(makeTicket({ last_message_text: null }))).toBe("");
  });
});

describe("snoozePresets", () => {
  // The next-Monday modulo is the easy-to-break part: from a Monday it must
  // go a full week out, from a Sunday just one day — get it wrong and a
  // ticket snoozes into the past and instantly resurfaces as snooze-elapsed.
  // Local-time strings so setHours-based math stays deterministic across TZs.
  it.each([
    ["Monday", "2026-07-13T15:00:00", "2026-07-20T09:00:00"],
    ["Friday", "2026-07-17T15:00:00", "2026-07-20T09:00:00"],
    ["Saturday", "2026-07-18T15:00:00", "2026-07-20T09:00:00"],
    ["Sunday", "2026-07-19T15:00:00", "2026-07-20T09:00:00"],
  ])("targets next Monday 9am from a %s", (_day, now, expected) => {
    const preset = snoozePresets(new Date(now)).find(
      (p) => p.id === "next-week",
    );
    expect(preset?.until).toEqual(new Date(expected));
  });

  it("keeps every preset in the future, even late at night", () => {
    const now = new Date("2026-07-15T23:30:00");
    for (const preset of snoozePresets(now)) {
      expect(preset.until.getTime()).toBeGreaterThan(now.getTime());
    }
  });
});
