import { beforeEach, describe, expect, it } from "vitest";
import { useTaskSelectionStore } from "./taskSelectionStore";

describe("taskSelectionStore", () => {
  beforeEach(() => {
    useTaskSelectionStore.setState({
      selectedTaskIds: [],
      lastClickedId: null,
    });
  });

  it("starts empty", () => {
    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
    expect(useTaskSelectionStore.getState().lastClickedId).toBeNull();
  });

  it("setSelectedTaskIds de-duplicates ids", () => {
    useTaskSelectionStore
      .getState()
      .setSelectedTaskIds(["t1", "t2", "t1", "t3", "t2"]);

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
      "t1",
      "t2",
      "t3",
    ]);
  });

  it("setSelectedTaskIds with a single id sets lastClickedId", () => {
    useTaskSelectionStore.getState().setSelectedTaskIds(["t1"]);

    expect(useTaskSelectionStore.getState().lastClickedId).toBe("t1");
  });

  it("setSelectedTaskIds with multiple ids preserves existing lastClickedId", () => {
    useTaskSelectionStore.setState({ lastClickedId: "t1" });
    useTaskSelectionStore.getState().setSelectedTaskIds(["t2", "t3"]);

    expect(useTaskSelectionStore.getState().lastClickedId).toBe("t1");
  });

  it("toggleTaskSelection adds an unselected task", () => {
    useTaskSelectionStore.getState().toggleTaskSelection("t1");

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["t1"]);
    expect(useTaskSelectionStore.getState().lastClickedId).toBe("t1");
  });

  it("toggleTaskSelection removes a selected task", () => {
    useTaskSelectionStore.setState({ selectedTaskIds: ["t1", "t2"] });

    useTaskSelectionStore.getState().toggleTaskSelection("t1");

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["t2"]);
    expect(useTaskSelectionStore.getState().lastClickedId).toBe("t1");
  });

  it("isTaskSelected reflects selection state", () => {
    useTaskSelectionStore.setState({ selectedTaskIds: ["t2"] });

    expect(useTaskSelectionStore.getState().isTaskSelected("t1")).toBe(false);
    expect(useTaskSelectionStore.getState().isTaskSelected("t2")).toBe(true);
  });

  it("clearSelection clears all selected tasks and lastClickedId", () => {
    useTaskSelectionStore.setState({
      selectedTaskIds: ["t1", "t2"],
      lastClickedId: "t2",
    });

    useTaskSelectionStore.getState().clearSelection();

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
    expect(useTaskSelectionStore.getState().lastClickedId).toBeNull();
  });

  it("pruneSelection keeps only visible task ids", () => {
    useTaskSelectionStore.setState({
      selectedTaskIds: ["t1", "t2", "t3"],
    });

    useTaskSelectionStore.getState().pruneSelection(["t2", "t4"]);

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["t2"]);
  });

  it("pruneSelection preserves array reference when nothing is pruned", () => {
    useTaskSelectionStore.setState({ selectedTaskIds: ["t1", "t2"] });
    const before = useTaskSelectionStore.getState().selectedTaskIds;

    useTaskSelectionStore.getState().pruneSelection(["t1", "t2", "t3"]);

    expect(useTaskSelectionStore.getState().selectedTaskIds).toBe(before);
  });

  describe("selectRange", () => {
    const orderedIds = ["t1", "t2", "t3", "t4", "t5"];

    it.each([
      { direction: "forward", anchor: "t2", target: "t4" },
      { direction: "backward", anchor: "t4", target: "t2" },
    ])(
      "selects a $direction range from anchor to target",
      ({ anchor, target }) => {
        useTaskSelectionStore.setState({ lastClickedId: anchor });

        useTaskSelectionStore.getState().selectRange(target, orderedIds);

        expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
          "t2",
          "t3",
          "t4",
        ]);
      },
    );

    it("merges range with existing selection", () => {
      useTaskSelectionStore.setState({
        selectedTaskIds: ["t1"],
        lastClickedId: "t3",
      });

      useTaskSelectionStore.getState().selectRange("t5", orderedIds);

      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
        "t1",
        "t3",
        "t4",
        "t5",
      ]);
    });

    it.each([
      { case: "no anchor", lastClickedId: null },
      { case: "anchor not in ordered list", lastClickedId: "t99" },
    ])("selects just the target when $case", ({ lastClickedId }) => {
      if (lastClickedId) {
        useTaskSelectionStore.setState({ lastClickedId });
      }

      useTaskSelectionStore.getState().selectRange("t3", orderedIds);

      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["t3"]);
    });

    it("uses fallbackAnchorId when there is no last-clicked anchor", () => {
      useTaskSelectionStore.getState().selectRange("t4", orderedIds, "t2");

      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
        "t2",
        "t3",
        "t4",
      ]);
      expect(useTaskSelectionStore.getState().lastClickedId).toBe("t4");
    });

    it("prefers lastClickedId over fallbackAnchorId when both are set", () => {
      useTaskSelectionStore.setState({ lastClickedId: "t3" });

      useTaskSelectionStore.getState().selectRange("t5", orderedIds, "t1");

      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
        "t3",
        "t4",
        "t5",
      ]);
    });

    it("updates lastClickedId to the target", () => {
      useTaskSelectionStore.setState({ lastClickedId: "t1" });

      useTaskSelectionStore.getState().selectRange("t3", orderedIds);

      expect(useTaskSelectionStore.getState().lastClickedId).toBe("t3");
    });
  });
});
