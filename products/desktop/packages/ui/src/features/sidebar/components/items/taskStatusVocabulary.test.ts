import { ArrowSquareIn, type Icon, SlackLogo } from "@phosphor-icons/react";
import { describe, expect, it } from "vitest";

import { taskBadges } from "./taskStatusVocabulary";

describe("taskBadges", () => {
  it.each([
    ["slack", SlackLogo],
    ["signals_scout", ArrowSquareIn],
    ["error_tracking", ArrowSquareIn],
  ])("marks a %s row with its source glyph", (originProduct, expected) => {
    const origin = taskBadges({ originProduct }).find(
      (badge) => badge.key === "origin",
    );

    expect(origin?.Icon).toBe(expected as Icon);
  });
});
