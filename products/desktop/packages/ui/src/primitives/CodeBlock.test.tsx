import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { HighlightedCode } from "@posthog/ui/primitives/HighlightedCode";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/themeStore", () => ({
  useThemeStore: (selector: (state: { isDarkMode: boolean }) => unknown) =>
    selector({ isDarkMode: false }),
}));

vi.mock("@posthog/ui/utils/syntax-highlight", () => ({
  highlightSyntax: () => null,
}));

function renderInTheme(ui: ReactElement) {
  return render(<Theme>{ui}</Theme>);
}

describe("CodeBlock copy", () => {
  it("copies plain string children", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderInTheme(
      <CodeBlock>
        <code>hello world</code>
      </CodeBlock>,
    );

    await userEvent.click(screen.getByLabelText("Copy code"));
    expect(writeText).toHaveBeenCalledWith("hello world");
  });

  it("copies source code from HighlightedCode children", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderInTheme(
      <CodeBlock>
        <HighlightedCode code="const x = 5;" language="typescript" />
      </CodeBlock>,
    );

    await userEvent.click(screen.getByLabelText("Copy code"));
    expect(writeText).toHaveBeenCalledWith("const x = 5;");
  });

  it("omits the copy button when showCopy is false", () => {
    renderInTheme(
      <CodeBlock showCopy={false}>
        <code>hello world</code>
      </CodeBlock>,
    );

    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });
});
