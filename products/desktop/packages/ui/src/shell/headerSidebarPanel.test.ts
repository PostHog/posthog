import {
  getHeaderSidebarPanelLayout,
  type HeaderSidebarPanelLayout,
} from "@posthog/ui/shell/headerSidebarPanel";
import { describe, expect, it } from "vitest";

describe("getHeaderSidebarPanelLayout", () => {
  it.each<{
    name: string;
    input: { sidebarOpen: boolean; sidebarWidth: number; isMac: boolean };
    expected: HeaderSidebarPanelLayout;
  }>([
    {
      name: "open on macOS tracks the sidebar width and keeps the divider",
      input: { sidebarOpen: true, sidebarWidth: 256, isMac: true },
      expected: {
        width: "256px",
        minWidth: "180px",
        paddingLeft: undefined,
        justify: "end",
        showBorder: true,
      },
    },
    {
      name: "open off macOS tracks the sidebar width",
      input: { sidebarOpen: true, sidebarWidth: 300, isMac: false },
      expected: {
        width: "300px",
        minWidth: "110px",
        paddingLeft: undefined,
        justify: "end",
        showBorder: true,
      },
    },
    {
      name: "collapsed on macOS reserves the traffic-light strip as left padding and drops the divider",
      input: { sidebarOpen: false, sidebarWidth: 256, isMac: true },
      expected: {
        width: "180px",
        minWidth: "180px",
        paddingLeft: "70px",
        justify: "start",
        showBorder: false,
      },
    },
    {
      name: "collapsed off macOS drops the divider and needs no traffic-light padding",
      input: { sidebarOpen: false, sidebarWidth: 256, isMac: false },
      expected: {
        width: "110px",
        minWidth: "110px",
        paddingLeft: undefined,
        justify: "start",
        showBorder: false,
      },
    },
  ])("$name", ({ input, expected }) => {
    expect(getHeaderSidebarPanelLayout(input)).toEqual(expected);
  });
});
