import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { type ReactNode, useLayoutEffect } from "react";

export function useSetHeaderContent(content: ReactNode) {
  const setContent = useHeaderStore((state) => state.setContent);

  useLayoutEffect(() => {
    setContent(content);

    return () => {
      setContent(null);
    };
  }, [content, setContent]);
}
