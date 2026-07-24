import { Box } from "@radix-ui/themes";

const TITLE_BAR_HEIGHT = 36;

/**
 * A draggable title bar for Electron windows: a draggable area at the top of
 * the window when using hidden title bars (e.g. the login screen).
 */
export function DraggableTitleBar() {
  return (
    <Box
      className="drag absolute top-0 right-0 left-0 z-10 w-full"
      style={{ height: TITLE_BAR_HEIGHT }}
    />
  );
}
