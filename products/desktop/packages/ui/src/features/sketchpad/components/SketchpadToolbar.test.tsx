import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useSketchpadViewStore } from "../interaction/sketchpadViewStore";
import { SketchpadToolbar } from "./SketchpadToolbar";

function Toolbar() {
  const { activePanel, setActivePanel } = useSketchpadViewStore();
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
    useSketchpadViewStore.getState().reset();
    const { getByLabelText, container, unmount } = render(<Toolbar />);
    for (const label of ["Library", "Agent", "History", "State"]) {
      fireEvent.click(getByLabelText(label));
      expect(getByLabelText(label)).toHaveAttribute("aria-pressed", "true");
      expect(container.querySelectorAll('[aria-pressed="true"]')).toHaveLength(
        1,
      );
    }
    fireEvent.click(getByLabelText("State"));
    expect(container.querySelectorAll('[aria-pressed="true"]')).toHaveLength(0);
    unmount();
    useSketchpadViewStore.getState().reset();
  });
});
