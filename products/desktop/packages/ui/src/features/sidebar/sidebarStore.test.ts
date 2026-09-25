import {
  ANY_SOURCE,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DESKTOP_SOURCE,
} from "@posthog/core/canvas/channelItems";
import { describe, expect, it } from "vitest";
import { useSidebarStore } from "./sidebarStore";

describe("sidebarStore", () => {
  it("rehydration sanitizes list item metadata fields", async () => {
    localStorage.setItem(
      "sidebar-storage",
      JSON.stringify({
        state: {
          listItemMetadataFields: ["creator", "unknown", "branch", "creator"],
        },
        version: 0,
      }),
    );

    await useSidebarStore.persist.rehydrate();

    expect(useSidebarStore.getState().listItemMetadataFields).toEqual([
      "creator",
      "branch",
    ]);
    localStorage.removeItem("sidebar-storage");
  });

  it.each([
    {
      label: "the old default",
      version: 0,
      source: ANY_SOURCE,
      expected: DESKTOP_SOURCE,
    },
    {
      label: "an old explicit source",
      version: 0,
      source: "slack",
      expected: "slack",
    },
    {
      label: "the new Any source choice",
      version: 1,
      source: ANY_SOURCE,
      expected: ANY_SOURCE,
    },
  ])("rehydration preserves $label", async ({ version, source, expected }) => {
    localStorage.setItem(
      "sidebar-storage",
      JSON.stringify({
        state: {
          channelItemFilters: {
            ...DEFAULT_CHANNEL_ITEM_FILTERS,
            source,
          },
        },
        version,
      }),
    );

    await useSidebarStore.persist.rehydrate();

    expect(useSidebarStore.getState().channelItemFilters.source).toBe(expected);
    localStorage.removeItem("sidebar-storage");
  });
});
