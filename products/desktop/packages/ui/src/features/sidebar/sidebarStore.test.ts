import { DEFAULT_CHANNEL_ITEM_FILTERS } from "@posthog/core/canvas/channelItems";
import { describe, expect, it } from "vitest";
import { useSidebarStore } from "./sidebarStore";

describe("sidebarStore", () => {
  it("persists channel item filters", () => {
    const filters = {
      ...DEFAULT_CHANNEL_ITEM_FILTERS,
      createdBy: "me" as const,
    };

    useSidebarStore.getState().setChannelItemFilters(filters);

    expect(
      JSON.parse(localStorage.getItem("sidebar-storage") ?? "{}"),
    ).toMatchObject({ state: { channelItemFilters: filters } });
    useSidebarStore.setState({
      channelItemFilters: DEFAULT_CHANNEL_ITEM_FILTERS,
    });
    localStorage.removeItem("sidebar-storage");
  });

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
});
