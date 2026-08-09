import { CaretDownIcon, CheckIcon } from "@phosphor-icons/react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import type { ReactNode } from "react";

export interface PillPickerItem {
  id: string;
  label: string;
  /** Tailwind background class for the dot left of the label. Omit where a
   *  colour has no meaning, e.g. snooze presets. */
  dotClass?: string;
  /** Marks the row holding the current value so the menu shows a tick. */
  current?: boolean;
  onSelect: () => void;
}

/**
 * Trigger pill plus menu for one editable ticket field. The trigger takes its
 * colour from the caller (status and priority are colour-coded by value); the
 * menu rows are styled here so the pickers can't drift apart.
 */
export function PillPicker({
  className,
  icon,
  label,
  ariaLabel,
  disabled,
  items,
}: {
  /** Background/text pair for the trigger, chosen per value. */
  className: string;
  icon?: ReactNode;
  label: string;
  ariaLabel: string;
  disabled?: boolean;
  items: PillPickerItem[];
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            disabled={disabled}
            aria-label={ariaLabel}
            className={`inline-flex cursor-pointer items-center gap-1 rounded-full px-2.5 py-1 font-medium text-[11px] leading-none disabled:cursor-default disabled:opacity-60 ${className}`}
          >
            {icon}
            <span>{label}</span>
            <CaretDownIcon size={10} className="opacity-70" />
          </button>
        }
      />
      <DropdownMenuContent align="end" side="bottom" sideOffset={6}>
        {items.map((item) => (
          <DropdownMenuItem key={item.id} onClick={item.onSelect}>
            <span className="flex min-w-0 flex-1 items-center gap-2">
              {item.dotClass && (
                <span
                  aria-hidden
                  className={`inline-block size-2 shrink-0 rounded-full ${item.dotClass}`}
                />
              )}
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.current && <CheckIcon size={12} className="shrink-0" />}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
