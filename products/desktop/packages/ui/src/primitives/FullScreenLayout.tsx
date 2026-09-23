import { Lifebuoy } from "@phosphor-icons/react";
import { DotPatternBackground } from "@posthog/ui/primitives/DotPatternBackground";
import { MathGridBackground } from "@posthog/ui/primitives/MathGridBackground";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Button, Flex, Theme } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { DraggableTitleBar } from "./DraggableTitleBar";

interface FullScreenLayoutProps {
  children: ReactNode;
  backgroundPattern?: "dots" | "grid";
  footerLeft?: ReactNode;
  footerRight?: ReactNode;
  /** Host-provided update banner shown in the default footer. */
  banner?: ReactNode;
  /** Host opens the support link. */
  onOpenSupport?: () => void;
  showFooter?: boolean;
  titleBarContent?: ReactNode;
}

export function FullScreenLayout({
  children,
  backgroundPattern = "dots",
  footerLeft,
  footerRight,
  banner,
  onOpenSupport,
  showFooter = true,
  titleBarContent,
}: FullScreenLayoutProps) {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);

  return (
    <Theme
      appearance={isDarkMode ? "dark" : "light"}
      accentColor={isDarkMode ? "yellow" : "orange"}
      radius="medium"
    >
      <Flex
        direction="column"
        height="100vh"
        className="relative overflow-hidden"
      >
        <DraggableTitleBar>{titleBarContent}</DraggableTitleBar>

        <div className="absolute inset-0 bg-(--color-background)" />
        {backgroundPattern === "grid" ? (
          <MathGridBackground />
        ) : (
          <DotPatternBackground />
        )}

        <Flex
          direction="column"
          flexGrow="1"
          className="relative z-[1] min-h-0 w-full"
        >
          <Flex
            direction="column"
            flexGrow="1"
            overflow="hidden"
            className="min-h-0"
          >
            {children}
          </Flex>

          {showFooter && (
            <Flex
              justify="between"
              className="absolute right-[32px] bottom-[20px] left-[32px] z-[2]"
            >
              {footerLeft ?? (
                <Flex align="center" gap="3">
                  <Button
                    size="1"
                    variant="ghost"
                    color="gray"
                    onClick={onOpenSupport}
                    className="opacity-50"
                  >
                    <Lifebuoy size={14} />
                    Get support
                  </Button>
                  {banner}
                </Flex>
              )}
              {footerRight ?? <div />}
            </Flex>
          )}
        </Flex>
      </Flex>
    </Theme>
  );
}
