import { render } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { useTaskSelectionStore } from "./taskSelectionStore";
import {
  SESSION_ROW_ATTRIBUTE,
  useMarqueeSelection,
} from "./useMarqueeSelection";

const ROW_HEIGHT = 20;

function Harness() {
  const ref = { current: null } as { current: HTMLDivElement | null };
  return <List innerRef={ref} />;
}

function List({ innerRef }: { innerRef: { current: HTMLDivElement | null } }) {
  const rect = useMarqueeSelection(innerRef);
  return (
    <div ref={innerRef} data-testid="anchor">
      <button type="button" data-testid="search">
        Search
      </button>
      {["a", "b", "c"].map((id) => (
        <button key={id} type="button" {...{ [SESSION_ROW_ATTRIBUTE]: id }}>
          {id}
        </button>
      ))}
      {rect ? <div data-testid="band" /> : null}
    </div>
  );
}

/**
 * jsdom gives every element a zero-sized box, so the rows are laid out here by
 * hand: row `i` occupies y = i*20 to (i+1)*20, and the anchor spans all three.
 */
function layout(container: HTMLElement) {
  const anchor = container.querySelector<HTMLElement>("[data-testid=anchor]");
  if (!anchor) throw new Error("anchor missing");
  anchor.getBoundingClientRect = () =>
    ({ top: 0, bottom: 60, left: 0, right: 100 }) as DOMRect;
  const rows = [
    ...container.querySelectorAll<HTMLElement>(`[${SESSION_ROW_ATTRIBUTE}]`),
  ];
  rows.forEach((row, i) => {
    row.getBoundingClientRect = () =>
      ({
        top: i * ROW_HEIGHT,
        bottom: (i + 1) * ROW_HEIGHT,
        left: 0,
        right: 100,
      }) as DOMRect;
  });
  return { anchor, rows };
}

function pointer(
  type: string,
  y: number,
  init: PointerEventInit = {},
): PointerEvent {
  return new PointerEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: 50,
    clientY: y,
    button: 0,
    buttons: 1,
    ...init,
  });
}

function drag(
  target: HTMLElement,
  fromY: number,
  toY: number,
  init: PointerEventInit = {},
) {
  act(() => {
    target.dispatchEvent(pointer("pointerdown", fromY, init));
    window.dispatchEvent(pointer("pointermove", toY, init));
    window.dispatchEvent(pointer("pointerup", toY, { ...init, buttons: 0 }));
  });
}

const selected = () => useTaskSelectionStore.getState().selectedTaskIds;

describe("useMarqueeSelection", () => {
  beforeEach(() => {
    useTaskSelectionStore.setState({
      selectedTaskIds: [],
      lastClickedId: null,
    });
  });

  it("selects every row the drag sweeps", () => {
    const { container } = render(<Harness />);
    const { anchor } = layout(container);

    drag(anchor, 58, 5);

    expect(selected()).toEqual(["a", "b", "c"]);
  });

  it("selects only the rows the drag reaches", () => {
    const { container } = render(<Harness />);
    const { anchor } = layout(container);

    drag(anchor, 58, 45);

    expect(selected()).toEqual(["c"]);
  });

  // A press on a row is that row's own: it opens the session, or drags it to a
  // command centre tile.
  it("ignores a drag that starts on a row", () => {
    const { container } = render(<Harness />);
    const { rows } = layout(container);

    drag(rows[2], 50, 5);

    expect(selected()).toEqual([]);
  });

  // Alt is the only modifier that takes a press away from its row. Cmd means
  // "add to the selection", which is the row's own click to answer.
  it("still ignores a drag from a row when Cmd is held", () => {
    const { container } = render(<Harness />);
    const { rows } = layout(container);

    drag(rows[2], 50, 5, { metaKey: true });

    expect(selected()).toEqual([]);
  });

  it("starts from a row when Alt says the drag is a selection", () => {
    const { container } = render(<Harness />);
    const { rows } = layout(container);

    drag(rows[2], 50, 5, { altKey: true });

    expect(selected()).toEqual(["a", "b", "c"]);
  });

  it("ignores a press on a control in the list", () => {
    const { container } = render(<Harness />);
    layout(container);
    const search = container.querySelector<HTMLElement>(
      "[data-testid=search]",
    ) as HTMLElement;

    drag(search, 58, 5);

    expect(selected()).toEqual([]);
  });

  it("leaves the selection alone when the pointer barely moves", () => {
    const { container } = render(<Harness />);
    const { anchor } = layout(container);
    useTaskSelectionStore.setState({ selectedTaskIds: ["b"] });

    drag(anchor, 58, 56);

    expect(selected()).toEqual(["b"]);
  });

  it("replaces what was selected before the drag", () => {
    const { container } = render(<Harness />);
    const { anchor } = layout(container);
    useTaskSelectionStore.setState({ selectedTaskIds: ["a"] });

    drag(anchor, 58, 45);

    expect(selected()).toEqual(["c"]);
  });

  it("adds to the selection when the modifier is held", () => {
    const { container } = render(<Harness />);
    const { anchor } = layout(container);
    useTaskSelectionStore.setState({ selectedTaskIds: ["a"] });

    drag(anchor, 58, 45, { metaKey: true });

    expect(selected()).toEqual(["a", "c"]);
  });
});
