import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
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
});

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
