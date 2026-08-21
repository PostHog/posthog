import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LinkDestinationBar } from "./LinkDestinationBar";
import { resolveLinkDestination } from "./linkDestination";

describe("resolveLinkDestination", () => {
  function elementFor(html: string, selector: string): Element {
    const host = document.createElement("div");
    host.innerHTML = html;
    const el = host.querySelector(selector);
    if (!el) throw new Error(`selector ${selector} not found`);
    return el;
  }

  it("returns the href of an absolute-URL anchor", () => {
    const el = elementFor(
      '<a href="https://github.com/PostHog/posthog/pull/87074/checks">PR</a>',
      "a",
    );
    expect(resolveLinkDestination(el)).toBe(
      "https://github.com/PostHog/posthog/pull/87074/checks",
    );
  });

  it("resolves from a descendant of the anchor", () => {
    const el = elementFor(
      '<a href="https://posthog.com"><span>PostHog</span></a>',
      "span",
    );
    expect(resolveLinkDestination(el)).toBe("https://posthog.com");
  });

  it("stays quiet for relative in-app hrefs and bare fragments", () => {
    expect(
      resolveLinkDestination(elementFor('<a href="/tasks/123">t</a>', "a")),
    ).toBeNull();
    expect(
      resolveLinkDestination(elementFor('<a href="#section">t</a>', "a")),
    ).toBeNull();
  });

  it("stays quiet for executable and internal schemes", () => {
    expect(
      resolveLinkDestination(
        elementFor("<a href=\"javascript:alert('x')\">t</a>", "a"),
      ),
    ).toBeNull();
    expect(
      resolveLinkDestination(elementFor('<a href="evidence:abc">t</a>', "a")),
    ).toBeNull();
  });

  it("shows deep links and mailto, which do tell the user where they go", () => {
    expect(
      resolveLinkDestination(
        elementFor('<a href="posthog-code://task/1">t</a>', "a"),
      ),
    ).toBe("posthog-code://task/1");
    expect(
      resolveLinkDestination(
        elementFor('<a href="mailto:hey@posthog.com">t</a>', "a"),
      ),
    ).toBe("mailto:hey@posthog.com");
  });

  it("lets non-anchor controls opt in via data-link-destination", () => {
    const el = elementFor(
      '<button type="button" data-link-destination="https://posthog.com/docs">docs</button>',
      "button",
    );
    expect(resolveLinkDestination(el)).toBe("https://posthog.com/docs");
  });

  it("lets an anchor suppress its preview with an empty data-link-destination", () => {
    const el = elementFor(
      '<a href="https://posthog.com" data-link-destination="">t</a>',
      "a",
    );
    expect(resolveLinkDestination(el)).toBeNull();
  });

  it("returns null for non-elements and plain elements", () => {
    expect(resolveLinkDestination(null)).toBeNull();
    expect(resolveLinkDestination(document)).toBeNull();
    expect(
      resolveLinkDestination(elementFor("<div>t</div>", "div")),
    ).toBeNull();
  });
});

describe("LinkDestinationBar", () => {
  const URL = "https://github.com/PostHog/posthog/pull/87074/checks";

  function setup() {
    return render(
      <div>
        <a href={URL}>the PR</a>
        <p>plain text</p>
        <LinkDestinationBar />
      </div>,
    );
  }

  it("shows the destination on hover and hides after the pointer leaves", async () => {
    setup();
    fireEvent.mouseOver(screen.getByText("the PR"));
    expect(await screen.findByText(URL)).toBeInTheDocument();

    // Moving onto a non-link hides the bar (after the anti-flicker delay).
    fireEvent.mouseOver(screen.getByText("plain text"));
    await waitFor(() => {
      expect(screen.queryByText(URL)).not.toBeInTheDocument();
    });
  });

  it("shows the destination when a link receives keyboard focus", async () => {
    setup();
    fireEvent.focusIn(screen.getByText("the PR"));
    expect(await screen.findByText(URL)).toBeInTheDocument();

    fireEvent.focusOut(screen.getByText("the PR"));
    await waitFor(() => {
      expect(screen.queryByText(URL)).not.toBeInTheDocument();
    });
  });

  it("announces politely: the viewport is an aria-live region that ignores pointer events", async () => {
    setup();
    fireEvent.mouseOver(screen.getByText("the PR"));
    await screen.findByText(URL);

    const viewport = screen.getByRole("region", { name: "Link destination" });
    expect(viewport).toHaveAttribute("aria-live", "polite");
    expect(viewport.className).toContain("pointer-events-none");
  });

  it("keeps one bar when moving between links, updating the text in place", async () => {
    const other = "https://posthog.com/docs";
    render(
      <div>
        <a href={URL}>first</a>
        <a href={other}>second</a>
        <LinkDestinationBar />
      </div>,
    );
    fireEvent.mouseOver(screen.getByText("first"));
    await screen.findByText(URL);
    fireEvent.mouseOver(screen.getByText("second"));
    expect(await screen.findByText(other)).toBeInTheDocument();
    expect(screen.queryByText(URL)).not.toBeInTheDocument();
  });
});
