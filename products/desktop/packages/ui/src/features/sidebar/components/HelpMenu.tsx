import {
  ArrowSquareOut,
  BookOpen,
  DiscordLogo,
  Gift,
  Globe,
  Keyboard,
  Question,
  ShieldCheck,
} from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { EXTERNAL_LINKS } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type HelpMenuItem,
} from "@posthog/shared/analytics-events";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useHoldSidebarPeek } from "@posthog/ui/features/sidebar/useHoldSidebarPeek";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useState } from "react";

interface HelpMenuProps {
  /** Where the trigger sits, which decides the side the menu opens on. */
  placement?: "rail" | "footer";
}

/** Docs, shortcuts, changelog, feedback, and our public links. */
export function HelpMenu({ placement = "rail" }: HelpMenuProps = {}) {
  const [open, setOpen] = useState(false);
  const holdPeek = useHoldSidebarPeek();
  const handleOpenChange = (next: boolean): void => {
    setOpen(next);
    holdPeek(next);
  };

  const inRail = placement === "rail";

  // Every row closes the menu, so the click is one step: record it, act, close.
  const run = (item: HelpMenuItem, action: () => void) => () => {
    track(ANALYTICS_EVENTS.HELP_MENU_ITEM_CLICKED, { item });
    action();
    setOpen(false);
  };

  return (
    <DropdownMenu open={open} onOpenChange={handleOpenChange}>
      <Tooltip>
        <TooltipTrigger
          render={
            <DropdownMenuTrigger
              render={
                <Button
                  variant="default"
                  size="icon"
                  aria-label="Help"
                  className="shrink-0 text-muted-foreground aria-expanded:bg-fill-active"
                >
                  <Question size={16} />
                </Button>
              }
            />
          }
        />
        <TooltipContent side={inRail ? "right" : "top"}>Help</TooltipContent>
      </Tooltip>

      <DropdownMenuContent
        className="w-56"
        side={inRail ? "right" : "top"}
        align="end"
        sideOffset={4}
      >
        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={run("documentation", () =>
              openExternalUrl(EXTERNAL_LINKS.docs),
            )}
          >
            <BookOpen size={14} className="text-gray-11" />
            Documentation
            <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={run("keyboard_shortcuts", () => openSettings("shortcuts"))}
          >
            <Keyboard size={14} className="text-gray-11" />
            Keyboard shortcuts
            <DropdownMenuShortcut>
              {formatHotkey(SHORTCUTS.SHORTCUTS_SHEET)}
            </DropdownMenuShortcut>
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={run("changelog", () => useWhatsNewStore.getState().open())}
          >
            <Gift size={14} className="text-gray-11" />
            View changelog
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={run("discord", () =>
              openExternalUrl(EXTERNAL_LINKS.discord),
            )}
          >
            <DiscordLogo size={14} className="text-gray-11" />
            Join our Discord
            <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={run("website", () =>
              openExternalUrl(EXTERNAL_LINKS.website),
            )}
          >
            <Globe size={14} className="text-gray-11" />
            Website
            <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={run("privacy", () =>
              openExternalUrl(EXTERNAL_LINKS.privacy),
            )}
          >
            <ShieldCheck size={14} className="text-gray-11" />
            Privacy policy
            <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
