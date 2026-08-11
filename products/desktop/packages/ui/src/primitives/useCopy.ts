import { useCallback, useState } from "react";

/**
 * Copy-to-clipboard with a transient `copied` flag for button feedback. Clipboard writes can reject
 * (blocked permission, unfocused document, insecure context) — the rejection is swallowed and
 * `copied` stays false, so the button never reports a success that didn't happen.
 */
export function useCopy(resetMs = 2000): {
  copied: boolean;
  copy: (text: string) => void;
} {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(
    (text: string) => {
      navigator.clipboard.writeText(text).then(
        () => {
          setCopied(true);
          setTimeout(() => setCopied(false), resetMs);
        },
        () => {},
      );
    },
    [resetMs],
  );
  return { copied, copy };
}
