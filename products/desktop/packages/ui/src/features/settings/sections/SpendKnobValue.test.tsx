import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SpendKnobValue } from "./SpendKnobValue";

async function typeAmount(
  user: ReturnType<typeof userEvent.setup>,
  amount: string,
): Promise<HTMLInputElement> {
  const input = screen.getByLabelText(/in dollars/i) as HTMLInputElement;
  await user.click(input);
  await user.clear(input);
  await user.type(input, amount);
  return input;
}

describe("SpendKnobValue", () => {
  it("discards the typed amount on Escape and restores the label", async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <SpendKnobValue
        valueUsd={20}
        label="$20"
        name="Daily warning"
        onCommit={onCommit}
      />,
    );

    const input = await typeAmount(user, "999");
    await user.keyboard("{Escape}");

    expect(onCommit).not.toHaveBeenCalled();
    expect(input).toHaveValue("$20");
  });

  it("commits the typed amount on Enter", async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <SpendKnobValue
        valueUsd={20}
        label="$20"
        name="Daily warning"
        onCommit={onCommit}
      />,
    );

    await typeAmount(user, "999");
    await user.keyboard("{Enter}");

    expect(onCommit).toHaveBeenCalledWith(999);
  });
});
