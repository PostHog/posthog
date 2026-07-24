import { HashIcon } from "@phosphor-icons/react";
import { Badge, Switch } from "@posthog/quill";
import { getSidebarItemPaddingLeft } from "../SidebarItem";

interface ContextsItemProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  depth?: number;
}

// A <label> rather than a nav Button so the Switch can live inside it
// without nesting buttons.
export function ContextsItem({
  checked,
  onCheckedChange,
  depth = 0,
}: ContextsItemProps) {
  return (
    <label
      htmlFor="channels-toggle"
      className="group flex w-full cursor-pointer items-center gap-2 rounded py-1 pr-2 text-[13px] leading-snug transition-colors hover:bg-fill-secondary"
      style={{ paddingLeft: getSidebarItemPaddingLeft(depth) }}
    >
      <span className="flex shrink-0 items-center opacity-80">
        <HashIcon size={14} />
      </span>
      <span className="min-w-0 truncate font-medium">Channels</span>
      <Badge variant="info">Alpha</Badge>
      <Switch
        id="channels-toggle"
        size="sm"
        className="ml-auto"
        checked={checked}
        onCheckedChange={onCheckedChange}
      />
    </label>
  );
}
