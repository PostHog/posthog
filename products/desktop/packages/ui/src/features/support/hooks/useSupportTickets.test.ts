import type {
  SupportTicket,
  SupportTicketPage,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  flattenSupportTicketPages,
  nextSupportTicketOffset,
} from "./useSupportTickets";

function page(ids: string[], count: number): SupportTicketPage {
  return { results: ids.map((id) => ({ id }) as SupportTicket), count };
}

describe("support ticket pagination", () => {
  it.each<[string, SupportTicketPage[], number | undefined]>([
    ["more tickets remain", [page(["a", "b"], 5)], 2],
    ["every ticket is loaded", [page(["a", "b"], 2)], undefined],
    ["a later page still leaves more", [page(["a"], 5), page(["b"], 5)], 2],
    [
      "later pages exhaust the queue",
      [page(["a"], 2), page(["b"], 2)],
      undefined,
    ],
    ["the count outlives its rows", [page(["a"], 9), page([], 9)], undefined],
  ])("stops requesting pages once %s", (_case, pages, expected) => {
    const lastPage = pages[pages.length - 1];
    expect(lastPage).toBeDefined();
    expect(nextSupportTicketOffset(lastPage as SupportTicketPage, pages)).toBe(
      expected,
    );
  });

  it("keeps a ticket once when paging shifts it across pages", () => {
    const tickets = flattenSupportTicketPages([
      page(["a", "b"], 3),
      page(["b", "c"], 3),
    ]);

    expect(tickets.map((ticket) => ticket.id)).toEqual(["a", "b", "c"]);
  });
});
