import { updateStore } from "@posthog/core/updates/updateStore";
import { ServiceProvider } from "@posthog/di/react";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useUpdateBannerStore } from "@posthog/ui/features/updates/updateBannerStore";
import {
  UPDATES_CLIENT,
  type UpdatesClient,
} from "@posthog/ui/features/updates/updatesClient";
import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { Theme } from "@radix-ui/themes";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Container } from "inversify";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UpdateBanner } from "./UpdateBanner";

registerRendererStateStorage({
  getItem: vi.fn().mockResolvedValue(null),
  setItem: vi.fn().mockResolvedValue(undefined),
  removeItem: vi.fn().mockResolvedValue(undefined),
});

const fakeUpdatesClient: UpdatesClient = {
  install: vi.fn().mockResolvedValue({ installed: true }),
  check: vi.fn(),
  isEnabled: vi.fn().mockResolvedValue({ enabled: true }),
  getStatus: vi.fn(),
  onStatus: () => ({ unsubscribe: () => {} }),
  onReady: () => ({ unsubscribe: () => {} }),
  onCheckFromMenu: () => ({ unsubscribe: () => {} }),
};

function renderBanner(variant?: "sidebar" | "compact") {
  const container = new Container();
  container.bind(UPDATES_CLIENT).toConstantValue(fakeUpdatesClient);
  return render(
    <ServiceProvider container={container}>
      <Theme>
        <UpdateBanner variant={variant} />
      </Theme>
    </ServiceProvider>,
  );
}

const VARIANTS = [
  { variant: "sidebar", readyText: "1.2.3 ready" },
  { variant: "compact", readyText: "1.2.3 ready — Restart" },
] as const;

function dismissButton() {
  return screen.queryByLabelText("Dismiss update banner");
}

async function expectBannerRemoved(text: string) {
  await waitFor(() => {
    expect(screen.queryByText(text)).toBeNull();
  });
}

describe("UpdateBanner", () => {
  beforeEach(() => {
    updateStore.setState({
      status: "ready",
      version: "1.2.3",
      availableVersion: "1.2.3",
      isEnabled: true,
    });
    useUpdateBannerStore.setState({ dismissedVersion: null });
    useSettingsStore.setState({ dismissibleUpdateBanners: false });
  });

  it.each(VARIANTS)(
    "shows no dismiss button in the $variant variant when the setting is off",
    ({ variant, readyText }) => {
      renderBanner(variant);

      expect(screen.getByText(readyText)).toBeInTheDocument();
      expect(dismissButton()).toBeNull();
    },
  );

  it.each(VARIANTS)(
    "dismisses the $variant variant when the setting is on",
    async ({ variant, readyText }) => {
      useSettingsStore.setState({ dismissibleUpdateBanners: true });
      renderBanner(variant);

      const dismiss = dismissButton();
      expect(dismiss).not.toBeNull();
      fireEvent.click(dismiss as HTMLElement);

      await expectBannerRemoved(readyText);
    },
  );

  it("keeps a dismissed version hidden across the update cycle", async () => {
    useSettingsStore.setState({ dismissibleUpdateBanners: true });
    updateStore.setState({
      status: "available",
      version: null,
      availableVersion: "1.2.3",
    });
    renderBanner();

    fireEvent.click(dismissButton() as HTMLElement);
    await expectBannerRemoved("Update available");

    act(() => {
      updateStore.setState({ status: "ready", version: "1.2.3" });
    });
    expect(screen.queryByText("1.2.3 ready")).toBeNull();
  });

  it("shows the banner again when a newer version arrives", async () => {
    useSettingsStore.setState({ dismissibleUpdateBanners: true });
    renderBanner();

    fireEvent.click(dismissButton() as HTMLElement);
    await expectBannerRemoved("1.2.3 ready");

    act(() => {
      updateStore.setState({ version: "1.2.4", availableVersion: "1.2.4" });
    });
    expect(screen.getByText("1.2.4 ready")).toBeInTheDocument();
  });

  it("restores a dismissed banner when the setting is turned off", async () => {
    useSettingsStore.setState({ dismissibleUpdateBanners: true });
    renderBanner();

    fireEvent.click(dismissButton() as HTMLElement);
    await expectBannerRemoved("1.2.3 ready");

    act(() => {
      useSettingsStore.setState({ dismissibleUpdateBanners: false });
    });
    expect(screen.getByText("1.2.3 ready")).toBeInTheDocument();
  });
});
