import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tileBeside, untileTracked } from "./tileActions";
import { useTileLayoutStore } from "./tileLayoutStore";

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

describe("tile analytics", () => {
  beforeEach(() => {
    vi.mocked(track).mockClear();
    useTileLayoutStore.setState({
      groups: [],
      activeByGroup: {},
      names: {},
      nextSplitNumber: 1,
    });
  });

  it("reports how many tabs the tile group holds", () => {
    tileBeside("b", "a", "right", "strip");
    expect(track).toHaveBeenLastCalledWith(ANALYTICS_EVENTS.BROWSER_TAB_TILED, {
      edge: "right",
      source: "strip",
      tile_count: 2,
    });

    tileBeside("c", "a", "bottom", "tile");
    expect(track).toHaveBeenLastCalledWith(ANALYTICS_EVENTS.BROWSER_TAB_TILED, {
      edge: "bottom",
      source: "tile",
      tile_count: 3,
    });

    untileTracked("c");
    expect(track).toHaveBeenLastCalledWith(
      ANALYTICS_EVENTS.BROWSER_TAB_UNTILED,
      { tile_count: 2 },
    );
  });
});
