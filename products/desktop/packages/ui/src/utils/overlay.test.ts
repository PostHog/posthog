import { afterEach, describe, expect, it } from "vitest";
import { hasOpenOverlay } from "./overlay";

describe("hasOpenOverlay", () => {
  let element: HTMLElement;

  afterEach(() => {
    element?.remove();
  });

  function addElement(tag: string, attrs: Record<string, string> = {}): void {
    element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      element.setAttribute(key, value);
    }
    document.body.appendChild(element);
  }

  it("returns false when no overlays exist", () => {
    expect(hasOpenOverlay()).toBe(false);
  });

  it("detects role=dialog", () => {
    addElement("div", { role: "dialog" });
    expect(hasOpenOverlay()).toBe(true);
  });

  it("detects role=alertdialog", () => {
    addElement("div", { role: "alertdialog" });
    expect(hasOpenOverlay()).toBe(true);
  });

  it("detects role=menu", () => {
    addElement("div", { role: "menu" });
    expect(hasOpenOverlay()).toBe(true);
  });

  it("detects data-radix-popper-content-wrapper", () => {
    addElement("div", { "data-radix-popper-content-wrapper": "" });
    expect(hasOpenOverlay()).toBe(true);
  });

  it("detects data-overlay", () => {
    addElement("div", { "data-overlay": "command-menu" });
    expect(hasOpenOverlay()).toBe(true);
  });

  it("does not false-positive on role=listbox (inline autocomplete)", () => {
    addElement("div", { role: "listbox" });
    expect(hasOpenOverlay()).toBe(false);
  });

  it("does not false-positive on role=tooltip", () => {
    addElement("div", { role: "tooltip" });
    expect(hasOpenOverlay()).toBe(false);
  });

  it("returns false after overlay is removed", () => {
    addElement("div", { role: "dialog" });
    expect(hasOpenOverlay()).toBe(true);
    element.remove();
    expect(hasOpenOverlay()).toBe(false);
  });
});
