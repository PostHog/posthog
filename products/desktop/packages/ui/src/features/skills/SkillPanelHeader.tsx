import { DotsThreeIcon, XIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@posthog/quill";
import type { ReactNode } from "react";
import { InlineEdit } from "./InlineEdit";

/** The one chip style used by every skill panel and list row. */
export function SkillChip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "positive";
}) {
  const toneClass =
    tone === "positive" ? "bg-green-3 text-green-11" : "bg-gray-3 text-gray-11";
  return (
    <span
      className={`flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ${toneClass}`}
    >
      {children}
    </span>
  );
}

interface SkillPanelHeaderProps {
  name: string;
  description?: string;
  /** Set to edit the name and the description in place. */
  onEdit?: (fields: { name?: string; description?: string }) => void;
  saving?: boolean;
  /** Small chips under the description. */
  badges?: ReactNode;
  /** Buttons shown before the menu. */
  actions?: ReactNode;
  menuItems?: ReactNode;
  onClose: () => void;
}

/**
 * One header for every skill sidebar. Every block starts on the panel's left
 * edge, so the title, the description, the chips and the body share one line.
 */
export function SkillPanelHeader({
  name,
  description,
  onEdit,
  saving,
  badges,
  actions,
  menuItems,
  onClose,
}: SkillPanelHeaderProps) {
  return (
    <div className="flex shrink-0 flex-col gap-1.5 border-gray-4 border-b px-3 py-2">
      <div className="flex items-center gap-1">
        <div className="min-w-0 flex-1">
          <InlineEdit
            value={name}
            placeholder="Name this skill"
            ariaLabel="skill name"
            textClass="truncate font-semibold text-[13px] text-gray-12"
            editable={!!onEdit}
            saving={saving}
            onSave={(next) => onEdit?.({ name: next })}
          />
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {actions}
          {menuItems ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    type="button"
                    variant="link-muted"
                    size="icon-sm"
                    aria-label="More actions"
                  >
                    <DotsThreeIcon size={16} weight="bold" />
                  </Button>
                }
              />
              <DropdownMenuContent align="end" className="min-w-[200px]">
                {menuItems}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          <Button
            type="button"
            variant="link-muted"
            size="icon-sm"
            aria-label="Close"
            onClick={onClose}
          >
            <XIcon size={14} />
          </Button>
        </div>
      </div>

      <InlineEdit
        value={description ?? ""}
        placeholder="Say when an agent must use this skill"
        ariaLabel="skill description"
        textClass="text-[12px] text-gray-10 leading-relaxed"
        multiline
        clamp
        editable={!!onEdit}
        saving={saving}
        onSave={(next) => onEdit?.({ description: next })}
      />

      {badges ? (
        <div className="flex flex-wrap items-center gap-1">{badges}</div>
      ) : null}
    </div>
  );
}
