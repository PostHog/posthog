import { BackgroundTileProvider } from "@posthog/ui/features/tab-tiling/backgroundTile";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { useSetHeaderContent } from "./useSetHeaderContent";

describe("useSetHeaderContent", () => {
  beforeEach(() => {
    useHeaderStore.setState({ content: null });
  });

  it("publishes the content and clears it on unmount", () => {
    const { unmount } = renderHook(() => useSetHeaderContent("Active page"));
    expect(useHeaderStore.getState().content).toBe("Active page");

    unmount();
    expect(useHeaderStore.getState().content).toBeNull();
  });

  it("leaves the active page's header alone from inside a background tile", () => {
    useHeaderStore.setState({ content: "Active page" });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <BackgroundTileProvider value={true}>{children}</BackgroundTileProvider>
    );
    const { unmount } = renderHook(
      () => useSetHeaderContent("Background page"),
      { wrapper },
    );
    expect(useHeaderStore.getState().content).toBe("Active page");

    unmount();
    expect(useHeaderStore.getState().content).toBe("Active page");
  });
});
