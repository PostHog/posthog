import type { Icon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";

export interface PanelSide<Key extends string> {
  key: Key;
  label: string;
  Icon: Icon;
}

const TOOLTIP_DELAY_MS = 400;

export function PanelSideSwitcher<Key extends string>({
  sides,
  active,
  onSelect,
}: {
  sides: readonly PanelSide<Key>[];
  active: Key | null;
  onSelect: (side: Key | null) => void;
}) {
  return (
    <TooltipProvider delay={TOOLTIP_DELAY_MS}>
      <div className="pointer-events-auto flex shrink-0 items-center gap-0.5">
        {sides.map(({ key, label, Icon }) => (
          <Tooltip key={key}>
            <TooltipTrigger
              render={
                <Button
                  variant="default"
                  size="icon-sm"
                  aria-label={label}
                  data-selected={active === key || undefined}
                  onClick={() => onSelect(active === key ? null : key)}
                  className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
                >
                  <Icon size={16} />
                </Button>
              }
            />
            <TooltipContent side="bottom">{label}</TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  );
}
