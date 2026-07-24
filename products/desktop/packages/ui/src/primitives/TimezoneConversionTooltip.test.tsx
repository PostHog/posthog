import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TimezoneConversionTooltip } from "./TimezoneConversionTooltip";

describe("TimezoneConversionTooltip", () => {
  it("falls back safely when given an invalid timezone", async () => {
    const portal = document.createElement("div");
    portal.id = "portal-container";
    document.body.append(portal);

    render(
      <TimezoneConversionTooltip
        timestamp="2026-07-23T01:00:00.000Z"
        timezone="Not/A_Timezone"
        open
      >
        <span>Next run</span>
      </TimezoneConversionTooltip>,
    );

    expect(screen.getByText("Next run")).toBeInTheDocument();
    expect(await screen.findByText("Schedule")).toBeInTheDocument();
    portal.remove();
  });
});
