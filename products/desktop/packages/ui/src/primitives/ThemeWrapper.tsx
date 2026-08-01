import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Theme } from "@radix-ui/themes";
import type React from "react";
import { useEffect, useRef } from "react";

let portalContainer: HTMLDivElement | null = null;

export function getPortalContainer(): HTMLElement {
  return portalContainer ?? document.body;
}

export function ThemeWrapper({ children }: { children: React.ReactNode }) {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const portalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    portalContainer = portalRef.current;
    return () => {
      portalContainer = null;
    };
  }, []);

  return (
    <Theme
      appearance={isDarkMode ? "dark" : "light"}
      accentColor={isDarkMode ? "yellow" : "orange"}
      grayColor="slate"
      panelBackground="solid"
      radius="medium"
      scaling="105%"
    >
      {children}
      <div ref={portalRef} id="portal-container" />
    </Theme>
  );
}
