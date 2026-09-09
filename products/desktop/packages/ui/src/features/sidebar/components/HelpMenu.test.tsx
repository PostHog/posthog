import { EXTERNAL_LINKS } from "@posthog/shared";
import { HelpMenu } from "@posthog/ui/features/sidebar/components/HelpMenu";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));
vi.mock("@posthog/ui/features/settings/hooks/useOpenSettings", () => ({
  openSettings: vi.fn(),
}));

const openMenu = async (): Promise<ReturnType<typeof userEvent.setup>> => {
  const user = userEvent.setup();
  render(<HelpMenu />);
  await user.click(screen.getByLabelText("Help"));
  return user;
};

describe("HelpMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWhatsNewStore.getState().close();
  });

  // These rows moved out of the account menu. Each one is the only way to
  // reach its destination from the shell, so a dropped handler strands it.
  it.each([
    { label: "Documentation", url: EXTERNAL_LINKS.docs },
    { label: "Join our Discord", url: EXTERNAL_LINKS.discord },
    { label: "Website", url: EXTERNAL_LINKS.website },
    { label: "Privacy policy", url: EXTERNAL_LINKS.privacy },
  ])("opens $label outside the app", async ({ label, url }) => {
    const user = await openMenu();

    await user.click(await screen.findByText(label));

    expect(openExternalUrl).toHaveBeenCalledWith(url);
  });

  it("opens the changelog dialog", async () => {
    const user = await openMenu();

    await user.click(await screen.findByText("View changelog"));

    expect(useWhatsNewStore.getState().isOpen).toBe(true);
  });
});
