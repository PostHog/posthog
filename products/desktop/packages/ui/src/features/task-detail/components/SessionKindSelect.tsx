import { ChatCircleText, Code, SquaresFour } from "@phosphor-icons/react";
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
import { useState } from "react";

/** What a new session in a space produces. */
export type SessionKind = "code" | "canvas" | "question";

export const DEFAULT_SESSION_KIND: SessionKind = "code";

const SESSION_KINDS: {
  kind: SessionKind;
  label: string;
  description: string;
  icon: React.ReactNode;
}[] = [
  {
    kind: "code",
    label: "Code",
    description: "Work in a repository and open a pull request",
    icon: <Code size={14} weight="regular" />,
  },
  {
    kind: "canvas",
    label: "Canvas",
    description: "Build an app or document from your PostHog data",
    icon: <SquaresFour size={14} weight="regular" />,
  },
  {
    kind: "question",
    label: "Question",
    description: "Get an answer, without changing anything",
    icon: <ChatCircleText size={14} weight="regular" />,
  },
];

/**
 * What the new session should produce — a chip for the composer's selector row,
 * drawn like the WorkspaceModeSelect beside it. Canvas sessions run in the
 * cloud without a repository, so picking one hides those chips.
 */
export function SessionKindSelect({
  value,
  onChange,
  disabled,
}: {
  value: SessionKind;
  onChange: (kind: SessionKind) => void;
  disabled?: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const current =
    SESSION_KINDS.find((item) => item.kind === value) ?? SESSION_KINDS[0];

  return (
    <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label="Session kind"
          >
            <span className="text-muted-foreground">{current.icon}</span>
            {current.label}
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="w-auto min-w-[280px]"
      >
        <DropdownMenuGroup>
          {SESSION_KINDS.map((item) => (
            <DropdownMenuItem
              key={item.kind}
              onClick={() => onChange(item.kind)}
              render={
                <ItemMenuItem size="xs" className="w-full">
                  <ItemMedia variant="icon" className="mt-2 ml-2">
                    <span>{item.icon}</span>
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
