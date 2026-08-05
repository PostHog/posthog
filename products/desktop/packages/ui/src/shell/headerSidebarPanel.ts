// The header's left region mirrors the sidebar: it holds the app-rail buttons
// (Bluebird) plus the sidebar toggle and lines up with the sidebar body below
// it. This helper derives its layout so the collapsed state stays clean — it
// clears the macOS traffic lights and drops the divider that would otherwise
// dangle as a stray edge over the page once the sidebar body has collapsed to
// zero width.

/** Width of the collapsed panel, sized to hold the app-rail + toggle buttons. */
const COLLAPSED_WIDTH = 110;
/**
 * Width of the macOS traffic-light strip (close / minimize / zoom). Reserved as
 * real left padding when collapsed so the buttons can never render underneath
 * the window controls.
 */
const MACOS_TRAFFIC_LIGHT_INSET = 70;

export interface HeaderSidebarPanelLayout {
  /** Inline width / minWidth for the panel (animates between the two states). */
  width: string;
  minWidth: string;
  /**
   * Left padding reserving the macOS traffic-light strip, or `undefined` when no
   * reservation is needed (open, or non-macOS).
   */
  paddingLeft: string | undefined;
  /**
   * Buttons hug the sidebar's right edge when open (matching the divider); when
   * collapsed they hug the left, after the traffic-light inset, so a wide
   * Bluebird label grows rightward into empty space rather than leftward under
   * the window controls.
   */
  justify: "start" | "end";
  /** The divider only belongs while the sidebar body is visible beneath it. */
  showBorder: boolean;
}

export function getHeaderSidebarPanelLayout({
  sidebarOpen,
  sidebarWidth,
  isMac,
}: {
  sidebarOpen: boolean;
  sidebarWidth: number;
  isMac: boolean;
}): HeaderSidebarPanelLayout {
  const collapsedWidth =
    COLLAPSED_WIDTH + (isMac ? MACOS_TRAFFIC_LIGHT_INSET : 0);
  return {
    width: sidebarOpen ? `${sidebarWidth}px` : `${collapsedWidth}px`,
    minWidth: `${collapsedWidth}px`,
    paddingLeft:
      !sidebarOpen && isMac ? `${MACOS_TRAFFIC_LIGHT_INSET}px` : undefined,
    justify: sidebarOpen ? "end" : "start",
    showBorder: sidebarOpen,
  };
}
