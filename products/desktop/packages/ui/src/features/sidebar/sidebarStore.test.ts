import {
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
      source: "any",
      expected: [DESKTOP_SOURCE],
    },
    {
      label: "an old explicit source",
      version: 0,
      source: "slack",
      expected: ["slack"],
    },
    {
      label: "the old Any source choice",
      version: 1,
      source: "any",
      expected: [],
    },
    {
      label: "an old single source",
      version: 1,
      source: "slack",
      expected: ["slack"],
    },
  ])("rehydration preserves $label", async ({ version, source, expected }) => {
    const { sources: _, ...filters } = DEFAULT_CHANNEL_ITEM_FILTERS;
    localStorage.setItem(
      "sidebar-storage",
      JSON.stringify({
        state: {
          channelItemFilters: { ...filters, source },
        },
        version,
      }),
    );

    await useSidebarStore.persist.rehydrate();

    const { channelItemFilters } = useSidebarStore.getState();
    expect(channelItemFilters.sources).toEqual(expected);
    expect(channelItemFilters).not.toHaveProperty("source");
    localStorage.removeItem("sidebar-storage");
  });
});
