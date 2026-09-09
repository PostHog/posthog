import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  SketchpadViewProvider,
  useSketchpadViewStore,
} from "../interaction/sketchpadViewStore";
import { SketchpadToolbar } from "./SketchpadToolbar";

function Toolbar() {
  const activePanel = useSketchpadViewStore((state) => state.activePanel);
  const setActivePanel = useSketchpadViewStore((state) => state.setActivePanel);
  return (
    <SketchpadToolbar
      zoom={1}
      activePanel={activePanel}
      onPanelChange={setActivePanel}
      onZoomIn={() => {}}
      onZoomOut={() => {}}
      onZoomReset={() => {}}
      onFitToContent={() => {}}
    />
  );
}

describe("SketchpadToolbar", () => {
  it("switches panels and closes the selected panel", () => {
    const { getByLabelText, container, unmount, rerender } = render(
      <SketchpadViewProvider key="board-a">
        <Toolbar />
      </SketchpadViewProvider>,
    );
    for (const label of ["Library", "Agent", "History", "State"]) {
      fireEvent.click(getByLabelText(label));
      expect(getByLabelText(label)).toHaveAttribute("aria-pressed", "true");
      expect(container.querySelectorAll('[aria-pressed="true"]')).toHaveLength(
        1,
      );
    }
    fireEvent.click(getByLabelText("State"));
    expect(container.querySelectorAll('[aria-pressed="true"]')).toHaveLength(0);
    fireEvent.click(getByLabelText("History"));
    rerender(
      <SketchpadViewProvider key="board-b">
        <Toolbar />
      </SketchpadViewProvider>,
    );
    expect(container.querySelectorAll('[aria-pressed="true"]')).toHaveLength(0);
    unmount();
  });
});
