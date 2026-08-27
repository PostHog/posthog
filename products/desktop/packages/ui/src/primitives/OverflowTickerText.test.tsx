import { act, render, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "./OverflowTickerText";

let reducedMotion = false;
vi.mock("framer-motion", async (importOriginal) => ({
  ...(await importOriginal<typeof import("framer-motion")>()),
  useReducedMotion: () => reducedMotion,
}));

afterEach(() => {
  reducedMotion = false;
  vi.restoreAllMocks();
});

// jsdom does no layout; report widths only for the ticker's overflow-hidden
// container so the mount-time measure sees the requested overflow.
function mockOverflow(overflowPx: number) {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("overflow-hidden") ? 200 : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("overflow-hidden") ? 200 + overflowPx : 0;
    },
  );
}

function renderTicker(reveal: boolean, overflowPx: number) {
  mockOverflow(overflowPx);
  const view = render(
    <OverflowTickerText reveal={reveal}>long title</OverflowTickerText>,
  );
  const tickerContainer = view.container.firstElementChild as HTMLElement;
  const content = tickerContainer.firstElementChild as HTMLElement;
  return { ...view, tickerContainer, content };
}

function endTransition(el: HTMLElement, propertyName: string) {
  const event = new Event("transitionend", { bubbles: true });
  Object.assign(event, { propertyName });
  act(() => {
    el.dispatchEvent(event);
  });
}

const FADE_IN = "transparent, black 24px";
const FADE_OUT = "black calc(100% - 24px), transparent";

describe("OverflowTickerText", () => {
  it.each([
    { name: "fitting text", overflowPx: 0, reveal: true, fades: [] },
    { name: "narrow text", overflowPx: -50, reveal: true, fades: [] },
    {
      name: "resting overflow",
      overflowPx: 40,
      reveal: false,
      fades: [FADE_OUT],
    },
    {
      name: "ticking overflow",
      overflowPx: 40,
      reveal: true,
      fades: [FADE_IN, FADE_OUT],
    },
    // A sliver of overflow keeps the resting mask: the text holds still, so
    // there is no head to fade in.
    {
      name: "overflow below the ticking threshold",
      overflowPx: 8,
      reveal: true,
      fades: [FADE_OUT],
    },
  ])("masks $name", ({ overflowPx, reveal, fades }) => {
    const { tickerContainer } = renderTicker(reveal, overflowPx);
    const mask = tickerContainer.style.maskImage ?? "";
    expect(mask.includes(FADE_IN)).toBe(fades.includes(FADE_IN));
    expect(mask.includes(FADE_OUT)).toBe(fades.includes(FADE_OUT));
  });

  it("scrolls exactly the overflow at constant speed", () => {
    const { content } = renderTicker(true, 40);
    expect(content.style.transform).toBe("translateX(-40px)");
    expect(content.style.transitionProperty).toBe("transform");
    expect(content.style.transitionTimingFunction).toBe("linear");
    expect(content.style.transitionDuration).toBe("0.8s");
  });

  it("snaps back without a transition when reveal ends", () => {
    const { rerender, content } = renderTicker(true, 40);
    rerender(
      <OverflowTickerText reveal={false}>long title</OverflowTickerText>,
    );
    expect(content.style.transform).toBe("translateX(0)");
    expect(content.style.transitionProperty).toBe("none");
  });

  it("drops the end fade once the scroll finishes", () => {
    const { tickerContainer, content } = renderTicker(true, 40);
    endTransition(content, "transform");
    const mask = tickerContainer.style.maskImage ?? "";
    expect(mask).toContain(FADE_IN);
    expect(mask).not.toContain(FADE_OUT);
  });

  it("ignores transition ends for other properties", () => {
    const { tickerContainer, content } = renderTicker(true, 40);
    endTransition(content, "opacity");
    expect(tickerContainer.style.maskImage ?? "").toContain(FADE_OUT);
  });

  it("ignores transition ends bubbled from children", () => {
    mockOverflow(40);
    const view = render(
      <OverflowTickerText reveal>
        <i data-testid="inner">long title</i>
      </OverflowTickerText>,
    );
    const tickerContainer = view.container.firstElementChild as HTMLElement;
    endTransition(view.getByTestId("inner"), "transform");
    expect(tickerContainer.style.maskImage ?? "").toContain(FADE_OUT);
  });

  it("restores both fades on the next reveal", () => {
    const { rerender, tickerContainer, content } = renderTicker(true, 40);
    endTransition(content, "transform");
    rerender(
      <OverflowTickerText reveal={false}>long title</OverflowTickerText>,
    );
    rerender(<OverflowTickerText reveal>long title</OverflowTickerText>);
    const mask = tickerContainer.style.maskImage ?? "";
    expect(mask).toContain(FADE_IN);
    expect(mask).toContain(FADE_OUT);
  });

  it("jumps straight to the end under reduced motion", () => {
    reducedMotion = true;
    const { tickerContainer, content } = renderTicker(true, 40);
    expect(content.style.transform).toBe("translateX(-40px)");
    expect(content.style.transitionProperty).toBe("none");
    const mask = tickerContainer.style.maskImage ?? "";
    expect(mask).toContain(FADE_IN);
    expect(mask).not.toContain(FADE_OUT);
  });
});

describe("useOverflowTickerReveal", () => {
  function focusEvent(matchesFocusVisible: boolean) {
    return {
      currentTarget: { matches: () => matchesFocusVisible },
    } as unknown as React.FocusEvent<HTMLElement>;
  }

  it("reveals while hovered", () => {
    const { result } = renderHook(() => useOverflowTickerReveal());
    expect(result.current.reveal).toBe(false);
    act(() => result.current.hoverProps.onPointerEnter());
    expect(result.current.reveal).toBe(true);
    act(() => result.current.hoverProps.onPointerLeave());
    expect(result.current.reveal).toBe(false);
  });

  it("reveals on keyboard focus until blur", () => {
    const { result } = renderHook(() => useOverflowTickerReveal());
    act(() => result.current.focusProps.onFocus(focusEvent(true)));
    expect(result.current.reveal).toBe(true);
    act(() => result.current.focusProps.onBlur());
    expect(result.current.reveal).toBe(false);
  });

  it("does not reveal on pointer-driven focus", () => {
    const { result } = renderHook(() => useOverflowTickerReveal());
    act(() => result.current.focusProps.onFocus(focusEvent(false)));
    expect(result.current.reveal).toBe(false);
  });
});
