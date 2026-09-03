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
});
