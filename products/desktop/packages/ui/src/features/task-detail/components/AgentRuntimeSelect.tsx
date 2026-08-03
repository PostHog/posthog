import { CaretDown, Terminal } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemMenuItem,
  ItemTitle,
} from "@posthog/quill";
import type { AgentRuntime } from "@posthog/shared";
import { useState } from "react";

interface AgentRuntimeSelectProps {
  value: AgentRuntime;
  onChange: (runtime: AgentRuntime) => void;
  disabled?: boolean;
}

const runtimes: Array<{
  runtime: AgentRuntime;
  label: string;
  description: string;
}> = [
  {
    runtime: "pi",
    label: "Pi",
    description: "PostHog's native Pi runtime",
  },
  {
    runtime: "acp",
    label: "ACP",
    description: "Agent Client Protocol runtime",
  },
];

export function AgentRuntimeSelect({
  value,
  onChange,
  disabled,
}: AgentRuntimeSelectProps) {
  const [open, setOpen] = useState(false);
  const selected =
    runtimes.find((item) => item.runtime === value) ?? runtimes[0];

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-label="Agent runtime"
          >
            <Terminal
              size={14}
              weight="regular"
              className="text-muted-foreground"
            />
            {selected.label}
            <CaretDown
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="min-w-[240px]"
      >
        <DropdownMenuGroup>
          {runtimes.map((item) => (
            <DropdownMenuItem
              key={item.runtime}
              onClick={() => {
                onChange(item.runtime);
                setOpen(false);
              }}
              render={
                <ItemMenuItem size="xs" className="w-full">
                  <ItemMedia variant="icon" className="mt-2 ml-2">
                    <Terminal size={14} weight="regular" />
                  </ItemMedia>
                  <ItemContent variant="menuItem">
                    <ItemTitle>{item.label}</ItemTitle>
                    <ItemDescription className="whitespace-nowrap leading-none">
                      {item.description}
                    </ItemDescription>
                  </ItemContent>
                </ItemMenuItem>
              }
            />
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
