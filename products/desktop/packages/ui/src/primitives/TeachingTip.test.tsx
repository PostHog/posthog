import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { Theme } from "@radix-ui/themes";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import {
  resetTeachingTips,
  retireTeachingTip,
  setTeachingTipsEnabled,
  TeachingTip,
} from "./TeachingTip";

// The store waits for a persistence backend before it shows anything; the host
// registers one at boot, and nothing does here.
beforeAll(() => {
  const values = new Map<string, string>();
  registerRendererStateStorage({
    getItem: (name) => values.get(name) ?? null,
    setItem: (name, value) => {
      values.set(name, value);
    },
    removeItem: (name) => {
      values.delete(name);
    },
  });
});

function renderTip(id: string, open: boolean) {
  return render(
    <Theme>
      <TeachingTip id={id} open={open} message="Artifacts placed here">
        <button type="button">Artifacts</button>
      </TeachingTip>
    </Theme>,
  );
}

describe("TeachingTip", () => {
  // Dismissing used to hold for the life of the view, so the second time a run
  // produced artifacts there was nothing to see and no way to get it back.
  it("comes back for the next moment after being dismissed", async () => {
    const { rerender } = renderTip("tip-dismissed", true);
    await screen.findByText("Artifacts placed here");

    fireEvent.click(screen.getByText("Dismiss"));
    await waitFor(() =>
      expect(screen.queryByText("Artifacts placed here")).toBeNull(),
    );

    const nextMoment = (open: boolean) =>
      rerender(
        <Theme>
          <TeachingTip
            id="tip-dismissed"
            open={open}
            message="Artifacts placed here"
          >
            <button type="button">Artifacts</button>
          </TeachingTip>
        </Theme>,
      );
    nextMoment(false);
    nextMoment(true);

    await screen.findByText("Artifacts placed here");
  });

  it("stays away once retired, including from outside the tip", async () => {
    retireTeachingTip("tip-retired");
    renderTip("tip-retired", true);

    await waitFor(() =>
      expect(screen.queryByText("Artifacts placed here")).toBeNull(),
    );
  });

  // The switch is one answer over every lesson, and turning it back on must
  // leave the per-lesson answers alone.
  it("teaches nothing while tips are switched off", async () => {
    const { rerender } = renderTip("tip-switched-off", true);
    await screen.findByText("Artifacts placed here");

    act(() => setTeachingTipsEnabled(false));
    await waitFor(() =>
      expect(screen.queryByText("Artifacts placed here")).toBeNull(),
    );

    act(() => setTeachingTipsEnabled(true));
    rerender(
      <Theme>
        <TeachingTip id="tip-switched-off" open message="Artifacts placed here">
          <button type="button">Artifacts</button>
        </TeachingTip>
      </Theme>,
    );
    await screen.findByText("Artifacts placed here");
  });

  // "Got it" is otherwise a one-way door, which is what settings offers a way
  // back from.
  it("offers a retired tip again after a reset", async () => {
    retireTeachingTip("tip-reset");
    renderTip("tip-reset", true);
    await waitFor(() =>
      expect(screen.queryByText("Artifacts placed here")).toBeNull(),
    );

    act(() => resetTeachingTips());

    await screen.findByText("Artifacts placed here");
  });
});
