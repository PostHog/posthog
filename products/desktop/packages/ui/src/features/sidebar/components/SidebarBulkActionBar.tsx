import {
  ArchiveIcon,
  FolderOpenIcon,
  PushPinIcon,
  PushPinSlashIcon,
  SquaresFourIcon,
  XIcon,
} from "@phosphor-icons/react";
import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import { sessionsLabel } from "@posthog/core/sidebar/selection";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import type { ReactElement, ReactNode } from "react";

interface SidebarBulkActionBarProps {
  actions: SidebarBulkActions;
  onClearSelection: () => void;
  onArchive: () => void;
}

/**
 * The sidebar is narrow and user-resizable, so the actions are icon buttons
 * with their full label in the tooltip rather than the labelled buttons the
 * inbox bar can afford.
 */
function ActionButton({
  label,
  disabledReason,
  loading,
  onClick,
  wrapTrigger,
  children,
}: {
  label: string;
  disabledReason: string | null;
  loading?: boolean;
  /** Absent when `wrapTrigger` supplies the behaviour, as a menu trigger does. */
  onClick?: () => void;
  /** Wraps the button before the tooltip does, e.g. to open a menu from it. */
  wrapTrigger?: (button: ReactElement) => ReactElement;
  children: ReactNode;
}): ReactElement {
  const disabled = disabledReason !== null || Boolean(loading);
  const button = (
    <Button
      type="button"
      size="icon-sm"
      variant="default"
      aria-label={label}
      disabled={disabled}
      loading={loading}
      onClick={onClick}
    >
      {children}
    </Button>
  );
  return (
    <Tooltip>
      <TooltipTrigger render={wrapTrigger ? wrapTrigger(button) : button} />
      <TooltipContent side="top">
        {disabledReason ? `Disabled because ${disabledReason}.` : label}
      </TooltipContent>
    </Tooltip>
  );
}

export function SidebarBulkActionBar({
  actions,
  onClearSelection,
  onArchive,
}: SidebarBulkActionBarProps): ReactElement {
  const {
    selectedCount,
    pinDirection,
    pinLabel,
    channels,
    archiveDisabledReason,
    pinDisabledReason,
    commandCenterDisabledReason,
    fileDisabledReason,
    isArchiving,
    isPinning,
    isFiling,
  } = actions;

  const sessions = sessionsLabel(selectedCount);

  return (
    <>
      {/* The bar is the only sign a selection exists, and it unmounts at zero.
          A live region announces reliably only if it was in the DOM before its
          text arrived, so this one sits outside the bar and outlives it. */}
      <span aria-live="polite" className="sr-only">
        {selectedCount > 0 ? `${sessions} selected` : ""}
      </span>

      {selectedCount > 0 && (
        <div className="flex items-center justify-between gap-2 border-(--gray-5) border-t bg-(--gray-2) px-2 py-1.5">
          <div className="flex min-w-0 items-center gap-1">
            <span className="shrink-0 font-medium text-(--gray-12) text-[12px]">
              {selectedCount} selected
            </span>
            <span className="truncate text-(--gray-10) text-[11px]">
              Esc to clear
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-0.5">
            <ActionButton
              label={pinLabel}
              disabledReason={pinDisabledReason}
              loading={isPinning}
              onClick={actions.pinSelected}
            >
              {pinDirection === "pin" ? (
                <PushPinIcon size={13} />
              ) : (
                <PushPinSlashIcon size={13} />
              )}
            </ActionButton>

            <ActionButton
              label={`Add ${sessions} to Command Center`}
              disabledReason={commandCenterDisabledReason}
              onClick={actions.addSelectedToCommandCenter}
            >
              <SquaresFourIcon size={13} />
            </ActionButton>

            {fileDisabledReason === null ? (
              <DropdownMenu>
                <ActionButton
                  label={`File ${sessions} to a channel`}
                  disabledReason={null}
                  loading={isFiling}
                  wrapTrigger={(button) => (
                    <DropdownMenuTrigger render={button} />
                  )}
                >
                  <FolderOpenIcon size={13} />
                </ActionButton>
                <DropdownMenuContent align="end">
                  {channels.map((channel) => (
                    <DropdownMenuItem
                      key={channel.id}
                      onClick={() => void actions.fileSelectedTo(channel.id)}
                    >
                      {channelDisplayLabel(channel.name, channel.channelType)}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}

            <ActionButton
              label={`Archive ${sessions}`}
              disabledReason={archiveDisabledReason}
              loading={isArchiving}
              onClick={onArchive}
            >
              <ArchiveIcon size={13} />
            </ActionButton>

            <ActionButton
              label="Clear selection"
              disabledReason={null}
              onClick={onClearSelection}
            >
              <XIcon size={13} />
            </ActionButton>
          </div>
        </div>
      )}
    </>
  );
}
