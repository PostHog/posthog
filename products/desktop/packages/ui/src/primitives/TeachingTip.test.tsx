import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { retireTeachingTip, TeachingTip } from "./TeachingTip";

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
});
