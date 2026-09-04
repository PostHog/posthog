import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PublicShareSection } from "./PublicShareSection";

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderSection(
  overrides: Partial<Parameters<typeof PublicShareSection>[0]> = {},
) {
  return render(
    <PublicShareSection
      sharing={{ enabled: false, accessToken: "tok" }}
      isLoading={false}
      isError={false}
      isPending={false}
      onToggle={vi.fn()}
      publicUrl="https://us.posthog.com/shared/tok"
      description="Anyone with the link can view."
      dataAttrPrefix="share-test"
      {...overrides}
    />,
  );
}

describe("PublicShareSection", () => {
  it.each([
    ["loading", { isLoading: true }, /Loading public sharing/],
    ["error", { isError: true }, /Couldn't load public sharing/],
  ])("shows the %s state instead of the toggle", (_name, overrides, text) => {
    renderSection(overrides);
    expect(screen.getByText(text)).toBeTruthy();
    expect(screen.queryByText("Share publicly")).toBeNull();
  });

  it("renders nothing when the backend cannot share this kind of thing", () => {
    const { container } = renderSection({ sharing: null });
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["off", false, false],
    ["on", true, true],
  ])(
    "only offers the public link while sharing is %s",
    (_name, enabled, expectLink) => {
      renderSection({ sharing: { enabled, accessToken: "tok" } });
      expect(screen.getByText("Share publicly")).toBeTruthy();
      expect(
        screen.queryByDisplayValue("https://us.posthog.com/shared/tok") !==
          null,
      ).toBe(expectLink);
    },
  );

  it("disables the switch while a toggle is in flight", () => {
    renderSection({ isPending: true });
    const toggle = screen.getByRole("switch");
    expect(
      toggle.hasAttribute("disabled") ||
        toggle.getAttribute("aria-disabled") === "true" ||
        toggle.hasAttribute("data-disabled"),
    ).toBe(true);
  });
});
