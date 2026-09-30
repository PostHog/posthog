import {
  DEFAULT_HINT_MAX,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { useRendererWindowFocusStore } from "@posthog/ui/shell/rendererWindowFocusStore";
import { Theme } from "@radix-ui/themes";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { TeachingTip } from "./TeachingTip";

const settings = () => useSettingsStore.getState();

beforeEach(() => {
  // The persisted answers are shared with the toast hints and with every other
  // test in the run, and nothing is taught until they have landed.
  useSettingsStore.setState({
    hints: {},
    tipsEnabled: true,
    _hasHydrated: true,
  });
  // Whether the test runner's document reports focus is beside the point of
  // every test that is not about it.
  useRendererWindowFocusStore.setState({ focused: true });
});

const windowInFront = (focused: boolean) =>
  act(() => useRendererWindowFocusStore.setState({ focused }));

function tip(id: string, open: boolean, moment?: number) {
  return (
    <Theme>
      <TeachingTip
        id={id}
        open={open}
        moment={moment}
        message="New artifacts show up here"
      >
        <button type="button">Artifacts</button>
      </TeachingTip>
    </Theme>
  );
}

const findTip = () => screen.findByText("New artifacts show up here");
const expectNoTip = () =>
  waitFor(() =>
    expect(screen.queryByText("New artifacts show up here")).toBeNull(),
  );

describe("TeachingTip", () => {
  // The caller's `open` can hold across several occasions (the artifacts mark
  // stays up until the panel is opened), so closing the tip without answering
  // it used to end the lesson for good with no way back.
  it("comes back for the next occasion after being closed unanswered", async () => {
    const { rerender } = render(tip("tip-closed", true, 1));
    await findTip();

    fireEvent.keyDown(document.body, { key: "Escape" });
    await expectNoTip();

    rerender(tip("tip-closed", true, 2));

    await findTip();
  });

  it("stays away for the next occasion once hidden", async () => {
    const { rerender } = render(tip("tip-hidden", true, 1));
    await findTip();

    fireEvent.click(screen.getByText("Hide"));
    await expectNoTip();

    rerender(tip("tip-hidden", true, 2));

    await expectNoTip();
  });

  // A lesson nobody answers must still end, or a recurring occasion (the
  // artifacts mark returns on every restart) nags forever. What runs out is
  // showings on screen, not occasions: one artifact a person ignores through
  // several turns puts the tip back up on each of them, and each one counts.
  it.each([
    ["a new artifact ends each showing", "dismissed" as const],
    ["one artifact outlasts several turns", "turn-restarted" as const],
  ])(
    "stops offering itself once it runs out of showings: %s",
    async (_ending, howShowingsEnd) => {
      // A turn starting takes the tip down and leaves `moment` where it was.
      const momentFor = (showing: number) =>
        howShowingsEnd === "dismissed" ? showing : 1;
      const { rerender } = render(tip("tip-counted", true, momentFor(1)));

      for (let showing = 1; showing <= DEFAULT_HINT_MAX; showing++) {
        rerender(tip("tip-counted", true, momentFor(showing)));
        await findTip();
        if (howShowingsEnd === "dismissed") {
          fireEvent.keyDown(document.body, { key: "Escape" });
        } else {
          rerender(tip("tip-counted", false, momentFor(showing)));
        }
        await expectNoTip();
      }

      rerender(tip("tip-counted", true, momentFor(DEFAULT_HINT_MAX + 1)));

      await expectNoTip();
    },
  );

  // Turns run long enough that people leave, and every one of them takes the
  // tip down and puts it back. Counting those would run the lesson out behind
  // another app's window, before anybody had a chance to read it.
  it("spends no showings while the window is not in front", async () => {
    windowInFront(false);
    const { rerender } = render(tip("tip-away", true, 1));

    for (let turn = 1; turn <= DEFAULT_HINT_MAX + 1; turn++) {
      rerender(tip("tip-away", false, turn));
      rerender(tip("tip-away", true, turn));
    }
    rerender(tip("tip-away", false, DEFAULT_HINT_MAX + 2));
    await expectNoTip();
    windowInFront(true);
    rerender(tip("tip-away", true, DEFAULT_HINT_MAX + 2));

    await findTip();
  });

  // Coming back to the window is not the tip appearing again; it is the same
  // one, still up, still unread.
  it("spends one showing however often the window loses focus", async () => {
    const { rerender } = render(tip("tip-flapping", true, 1));
    await findTip();

    for (let flap = 0; flap < DEFAULT_HINT_MAX; flap++) {
      windowInFront(false);
      windowInFront(true);
    }
    rerender(tip("tip-flapping", false, 1));
    await expectNoTip();
    rerender(tip("tip-flapping", true, 2));

    await findTip();
  });

  // "Hide" writes the same `hints` entry the toast hints answer, so a lesson
  // learned from either surface ends for both.
  it("stays away once learned from outside the tip", async () => {
    act(() => settings().markHintLearned("tip-learned"));
    render(tip("tip-learned", true));

    await expectNoTip();
  });

  // Otherwise every restart flashes the tips someone has already hidden,
  // between the first render and the persisted answers landing.
  it("teaches nothing before the persisted answers have landed", async () => {
    act(() => useSettingsStore.setState({ _hasHydrated: false }));
    render(tip("tip-unhydrated", true));

    await expectNoTip();
  });

  // The switch is one answer over every lesson, and turning it back on must
  // leave the per-lesson answers alone.
  it("teaches nothing while tips are switched off", async () => {
    const { rerender } = render(tip("tip-switched-off", true));
    await findTip();

    act(() => settings().setTipsEnabled(false));
    await expectNoTip();

    act(() => settings().setTipsEnabled(true));
    rerender(tip("tip-switched-off", true));

    await findTip();
  });

  // Hiding is otherwise a one-way door, which is what settings offers a way
  // back from.
  it("offers a hidden tip again after a reset", async () => {
    act(() => settings().markHintLearned("tip-reset"));
    render(tip("tip-reset", true));
    await expectNoTip();

    act(() => settings().resetHints());

    await findTip();
  });
});
