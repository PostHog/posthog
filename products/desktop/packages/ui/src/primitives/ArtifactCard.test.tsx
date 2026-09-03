import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArtifactCard } from "./ArtifactCard";

describe("ArtifactCard", () => {
  it("is an interactive button when it can open", () => {
    render(<ArtifactCard icon={null} title="report.csv" onOpen={() => {}} />);

    const card = screen.getByRole("button", { name: "View report.csv" });
    expect(card).toHaveAttribute("tabindex", "0");
    expect(card).not.toHaveAttribute("aria-disabled");
  });

  it("stays a plain container with active actions when it cannot open", () => {
    render(
      <ArtifactCard
        icon={null}
        title="report.csv"
        actions={
          <button type="button" onClick={() => {}}>
            See all
          </button>
        }
      />,
    );

    // No button role or disabled state on the inert card, so the action inside
    // it is not inherited as disabled by assistive technology.
    expect(
      screen.queryByRole("button", { name: "View report.csv" }),
    ).toBeNull();
    const card = screen.getByText("report.csv").closest("[data-artifact-card]");
    expect(card).not.toHaveAttribute("role");
    expect(card).not.toHaveAttribute("aria-disabled");
    expect(screen.getByRole("button", { name: "See all" })).toBeEnabled();
  });
});
