import { ApiRequestError } from "@posthog/api-client/fetcher";
import type {
  Ticket,
  TicketMessage,
  TicketView,
} from "@posthog/api-client/posthog-client";
import {
  type ClassifiedTicket,
  SLA_AT_RISK_WINDOW_MS,
} from "@posthog/core/support/attention";
import { describe, expect, it } from "vitest";
import {
  applyQueueSort,
  assigneeDisplay,
  channelLabel,
  customerTicketHistory,
  EMPTY_QUEUE_FILTERS,
  groupSavedViews,
  hasPriority,
  isUnknownSavedViewError,
  priorityLabel,
  type QueueFilters,
  type QueueSortField,
  queueFilterChips,
  queueListOptions,
  requesterLabel,
  SAVED_VIEW_SEARCH_THRESHOLD,
  slaCountdownLabel,
  slaTone,
  snoozePresets,
  statusLabel,
  ticketActivityEntries,
  ticketPreview,
  visibleQueueColumns,
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

describe("slaTone", () => {
  const now = new Date("2026-07-15T12:00:00Z");
  const at = (offsetMs: number) =>
    new Date(now.getTime() + offsetMs).toISOString();

  // The stripe colour and the queue tier must agree: if the at-risk band ever
  // drifts from SLA_AT_RISK_WINDOW_MS, rows get ranked as urgent while showing
  // a calm green stripe (or the reverse).
  it.each([
    ["no due date", null, "none"],
    ["unparseable", "not-a-date", "none"],
    ["past due", at(-1), "breached"],
    ["exactly due", at(0), "at-risk"],
    [
      "one ms inside the at-risk window",
      at(SLA_AT_RISK_WINDOW_MS - 1),
      "at-risk",
    ],
    ["exactly at the window edge", at(SLA_AT_RISK_WINDOW_MS), "at-risk"],
    ["one ms outside the window", at(SLA_AT_RISK_WINDOW_MS + 1), "on-track"],
  ] as const)("is %s → %s", (_case, dueAt, expected) => {
    expect(slaTone(dueAt, now)).toBe(expected);
  });
});

describe("slaCountdownLabel", () => {
  const now = new Date("2026-07-15T12:00:00Z");
  const at = (offsetMs: number) =>
    new Date(now.getTime() + offsetMs).toISOString();

  it.each([
    [30 * 60_000, "30m left"],
    [-30 * 60_000, "30m overdue"],
    [3 * 60 * 60_000, "3h left"],
    // The label must roll over to days before "72h" shows up.
    [72 * 60 * 60_000, "3d left"],
  ])("labels a %sms offset as %s", (offset, expected) => {
    expect(slaCountdownLabel(at(offset), now)).toBe(expected);
  });

  it("has no label without a due date", () => {
    expect(slaCountdownLabel(null, now)).toBeNull();
  });
});

describe("visibleQueueColumns", () => {
  it("always includes the customer column, whatever is stored", () => {
    expect(visibleQueueColumns([]).map((c) => c.id)).toEqual(["customer"]);
  });

  // Stored ids accumulate in toggle order; the list must still render in the
  // canonical order or the header and the cells drift apart.
  it("returns canonical order regardless of toggle order", () => {
    expect(
      visibleQueueColumns(["updated", "number", "sla"]).map((c) => c.id),
    ).toEqual(["number", "customer", "sla", "updated"]);
  });
});

describe("applyQueueSort", () => {
  const ranked = (tickets: Ticket[]): ClassifiedTicket[] =>
    tickets.map((ticket) => ({ ticket, state: "in-progress" as const }));

  const numbers = (rows: ClassifiedTicket[]) =>
    rows.map((row) => row.ticket.ticket_number);

  it("keeps the attention ranking when no column sort is set", () => {
    const rows = ranked([
      makeTicket({ ticket_number: 3, priority: "low" }),
      makeTicket({ ticket_number: 1, priority: "high" }),
    ]);
    expect(numbers(applyQueueSort(rows, null))).toEqual([3, 1]);
  });

  // Untriaged is unknown urgency, not the bottom of the scale — a plain
  // enum ordering would bury triage debt below every "low" ticket.
  it.each([
    [false, [2, 4, 3, 1]],
    [true, [1, 3, 4, 2]],
  ])("orders unset priority above low (desc=%s)", (desc, expected) => {
    const rows = ranked([
      makeTicket({ ticket_number: 1, priority: "high" }),
      makeTicket({ ticket_number: 2, priority: "low" }),
      makeTicket({ ticket_number: 3, priority: "medium" }),
      makeTicket({ ticket_number: 4, priority: null }),
    ]);
    expect(numbers(applyQueueSort(rows, { field: "priority", desc }))).toEqual(
      expected,
    );
  });

  // Absent values are not "the largest value": flipping direction must not
  // float tickets with no deadline (or no owner) to the top of the queue.
  it.each([
    ["sla_due_at", { sla_due_at: "2026-07-15T10:00:00Z" }, {}],
    [
      "assignee",
      {
        assignee: {
          id: "a",
          type: "user",
          user: { first_name: "Ada" },
          role: null,
        },
      },
      {},
    ],
  ] as const)(
    "keeps missing %s at the end in both directions",
    (field, present, absent) => {
      const rows = ranked([
        makeTicket({ ticket_number: 1, ...absent, assignee: undefined }),
        makeTicket({ ticket_number: 2, ...present }),
      ]);
      for (const desc of [false, true]) {
        const sorted = applyQueueSort(rows, {
          field: field as QueueSortField,
          desc,
        });
        expect(numbers(sorted).at(-1)).toBe(1);
      }
    },
  );

  it("leaves rows that tie on the sorted column in attention order", () => {
    const rows = ranked([
      makeTicket({ ticket_number: 9, priority: "high" }),
      makeTicket({ ticket_number: 2, priority: "high" }),
    ]);
    expect(
      numbers(applyQueueSort(rows, { field: "priority", desc: true })),
    ).toEqual([9, 2]);
  });
});

describe("queueFilterChips", () => {
  const views = [
    { short_id: "v1", name: "Escalations" },
  ] as unknown as TicketView[];

  const filters: QueueFilters = {
    view: "v1",
    status: "open",
    priority: "high",
    channel: "slack",
    sla: "breached",
    assignee: "unassigned",
    search: "  billing  ",
  };

  it("labels the applied view alongside every applied filter", () => {
    expect(queueFilterChips(filters, views).map((chip) => chip.label)).toEqual([
      "View: Escalations",
      "Status: Open",
      "Priority: High",
      "Channel: Slack",
      "SLA: Breached",
      "Assignee: Unassigned",
      "Search: billing",
    ]);
  });

  // Removing one chip must clear exactly that filter — the bug this catches is
  // a chip that resets the whole filter set (or the wrong key). The view is in
  // the matrix because it shares the mechanism but is not a filter param.
  it.each([
    "view",
    "status",
    "priority",
    "channel",
    "sla",
    "assignee",
    "search",
  ])("removing the %s chip clears only that filter", (id) => {
    const chip = queueFilterChips(filters, views).find((c) => c.id === id);
    const next = chip?.next as QueueFilters;
    expect(queueFilterChips(next, views).map((c) => c.id)).toEqual(
      queueFilterChips(filters, views)
        .map((c) => c.id)
        .filter((other) => other !== id),
    );
  });

  // A view whose name hasn't loaded — or that was deleted elsewhere — must
  // still get a chip. Hiding it would leave the queue silently scoped with no
  // on-screen way back to all tickets.
  it("still chips an applied view whose name is unresolved", () => {
    const chips = queueFilterChips(
      { ...EMPTY_QUEUE_FILTERS, view: "gone" },
      [],
    );
    expect(chips.map((chip) => chip.label)).toEqual(["View: gone"]);
    expect(chips[0].next.view).toBeNull();
  });

  it("ignores a whitespace-only search", () => {
    expect(queueFilterChips({ ...EMPTY_QUEUE_FILTERS, search: "   " })).toEqual(
      [],
    );
  });
});

describe("queueListOptions", () => {
  it("sends only the filters that are set", () => {
    expect(queueListOptions(EMPTY_QUEUE_FILTERS)).toEqual({
      orderBy: "-updated_at",
    });
  });

  it("maps every chip onto its endpoint parameter", () => {
    expect(
      queueListOptions({
        view: "v1",
        status: "pending",
        priority: "medium",
        channel: "email",
        sla: "at-risk",
        assignee: "me",
        search: " refund ",
      }),
    ).toEqual({
      orderBy: "-updated_at",
      // Sent alongside the filters, not instead of them: the server expands the
      // view and then merges these over it, so ad-hoc filters refine a view.
      view: "v1",
      status: "pending",
      priority: "medium",
      channelSource: "email",
      sla: "at-risk",
      assignee: "me",
      search: "refund",
    });
  });
});

describe("groupSavedViews", () => {
  const view = (name: string, is_favorited = false) =>
    ({ short_id: name.toLowerCase(), name, is_favorited }) as TicketView;

  // The bug this catches: filtering the whole list before partitioning, so
  // typing in the rail's search box makes your favorites disappear — exactly
  // the views you favorited to keep within reach.
  it("keeps favorited views out of the search filter", () => {
    const groups = groupSavedViews(
      [view("Escalations", true), view("Billing"), view("Onboarding")],
      "bill",
    );
    expect(groups.favorited.map((v) => v.name)).toEqual(["Escalations"]);
    expect(groups.other.map((v) => v.name)).toEqual(["Billing"]);
  });

  it.each([
    ["exact", "Billing", true],
    ["case-insensitive", "bILLing", true],
    ["padded", "  billing  ", true],
    ["substring", "ill", true],
    ["unmatched", "refunds", false],
  ])("handles a %s query (%s)", (_case, search, matches) => {
    const groups = groupSavedViews([view("Billing")], search);
    expect(groups.other).toHaveLength(matches ? 1 : 0);
    expect(groups.noMatches).toBe(!matches);
  });

  // Off-by-one here is the difference between a search box over four views
  // (pure chrome) and no search box over a rail you have to scroll.
  it.each([
    [SAVED_VIEW_SEARCH_THRESHOLD - 1, false],
    [SAVED_VIEW_SEARCH_THRESHOLD, false],
    [SAVED_VIEW_SEARCH_THRESHOLD + 1, true],
  ])("shows the search box for %s views: %s", (count, expected) => {
    const views = Array.from({ length: count }, (_, i) => view(`View ${i}`));
    expect(groupSavedViews(views, "").showSearch).toBe(expected);
  });

  it("reports no matches only once something has been typed", () => {
    expect(groupSavedViews([], "").noMatches).toBe(false);
  });
});

describe("isUnknownSavedViewError", () => {
  // Too wide and a genuinely broken request silently clears the view and hides
  // the real error; too narrow and a deleted view wedges the queue on an error
  // the user can't clear.
  it.each([
    [
      "a 400 naming the view field",
      400,
      { view: "No saved ticket view…" },
      true,
    ],
    ["a 400 about something else", 400, { status: "Invalid status." }, false],
    ["a 500 mentioning view", 500, { view: "boom" }, false],
  ] as const)("is %s → %s", (_case, status, body, expected) => {
    const error = new ApiRequestError(status, JSON.stringify(body), body);
    expect(isUnknownSavedViewError(error)).toBe(expected);
  });

  it.each([[new Error("network down")], [null], ["nope"]])(
    "is false for a non-API error (%s)",
    (error) => {
      expect(isUnknownSavedViewError(error)).toBe(false);
    },
  );
});

describe("ticketActivityEntries", () => {
  const message = (overrides: Partial<TicketMessage>): TicketMessage => ({
    id: "m-1",
    content: "hi",
    rich_content: null,
    author_type: "customer",
    author_name: "Grace",
    is_private: false,
    created_at: "2026-07-02T00:00:00Z",
    ...overrides,
  });

  it("reports the newest event first and tells a note from a public reply", () => {
    const entries = ticketActivityEntries(
      makeTicket({ created_at: "2026-07-01T00:00:00Z", email_from: "g@x.com" }),
      [
        message({ id: "m-1", created_at: "2026-07-02T00:00:00Z" }),
        message({
          id: "m-2",
          author_type: "agent",
          author_name: "Ada",
          created_at: "2026-07-03T00:00:00Z",
        }),
        message({
          id: "m-3",
          author_type: "agent",
          author_name: "Ada",
          is_private: true,
          created_at: "2026-07-04T00:00:00Z",
        }),
      ],
    );
    expect(entries.map((entry) => entry.id)).toEqual([
      "internal-note",
      "team-replied",
      "customer-wrote",
      "opened",
    ]);
  });

  it("reports the opening event alone while the thread is still loading", () => {
    expect(ticketActivityEntries(makeTicket(), undefined)).toHaveLength(1);
  });
});

describe("customerTicketHistory", () => {
  const current = makeTicket({
    id: "current",
    ticket_number: 1,
    email_from: "Grace@Example.com",
    updated_at: "2026-07-02T00:00:00Z",
  });

  // The search that backs this card can page the open ticket out; without the
  // merge the card reads as if the ticket you're looking at doesn't exist.
  it("includes the current ticket when the fetched page omits it", () => {
    const { entries } = customerTicketHistory(
      [
        makeTicket({
          id: "older",
          ticket_number: 2,
          email_from: "grace@example.com",
          updated_at: "2026-07-01T00:00:00Z",
        }),
      ],
      current,
      10,
    );
    expect(entries.map((entry) => entry.ticket.id)).toEqual([
      "current",
      "older",
    ]);
    expect(entries[0].isCurrent).toBe(true);
  });

  it("drops tickets that belong to someone else", () => {
    const { entries } = customerTicketHistory(
      [makeTicket({ id: "other", email_from: "someone@else.com" })],
      current,
      10,
    );
    expect(entries.map((entry) => entry.ticket.id)).toEqual(["current"]);
  });

  it("caps the list and reports how many are hidden", () => {
    const others = Array.from({ length: 4 }, (_, index) =>
      makeTicket({
        id: `t-${index}`,
        ticket_number: index + 10,
        email_from: "grace@example.com",
        updated_at: `2026-07-0${index + 3}T00:00:00Z`,
      }),
    );
    const { entries, extra } = customerTicketHistory(others, current, 2);
    expect(entries).toHaveLength(2);
    expect(extra).toBe(3);
  });
});
