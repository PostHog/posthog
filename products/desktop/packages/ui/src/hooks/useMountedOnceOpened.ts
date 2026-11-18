import { useState } from "react";

// Dialogs rendered per list row are expensive to mount even while closed, so
// callers gate them on this: false until the first open, true from then on so
// close transitions keep their element.
export function useMountedOnceOpened(open: boolean): boolean {
  const [mounted, setMounted] = useState(open);
  if (open && !mounted) setMounted(true);
  return mounted || open;
}
