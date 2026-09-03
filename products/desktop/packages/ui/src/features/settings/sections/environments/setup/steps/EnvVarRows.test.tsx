import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EnvVarRows } from "./EnvVarRows";

describe("EnvVarRows", () => {
  it("lists the variables already saved instead of reading as empty", () => {
    render(
      <EnvVarRows
        rows={[]}
        savedKeys={["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("ANTHROPIC_API_KEY")).toBeTruthy();
    expect(screen.getByText("OPENAI_API_KEY")).toBeTruthy();
    expect(screen.queryByText(/None yet/)).toBeNull();
  });

  it("says nothing is set only when nothing is", () => {
    render(<EnvVarRows rows={[]} onChange={() => {}} />);
    expect(screen.getByText(/None yet/)).toBeTruthy();
  });

  it("warns that entered rows replace the saved variables", () => {
    render(
      <EnvVarRows
        rows={[{ id: "a", key: "OPENAI_API_KEY", value: "sk-test" }]}
        savedKeys={["ANTHROPIC_API_KEY"]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/replaces the variables/)).toBeTruthy();
    expect(screen.getByText(/ANTHROPIC_API_KEY/)).toBeTruthy();
  });

  it("adds a pasted .env without the keys the sandbox manages", async () => {
    const onChange = vi.fn();
    render(
      <EnvVarRows
        rows={[{ id: "a", key: "", value: "" }]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText("Variable 1 name"));
    await userEvent.paste(
      "OPENAI_API_KEY=sk-example\nGITHUB_TOKEN=ghp-example",
    );

    expect(onChange).toHaveBeenCalledWith([
      { id: expect.any(String), key: "OPENAI_API_KEY", value: "sk-example" },
    ]);
    expect(screen.getByText(/GITHUB_TOKEN/)).toBeTruthy();
  });
});
