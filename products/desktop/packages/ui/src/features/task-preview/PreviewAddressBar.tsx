import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import {
  Button,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useEffect, useState } from "react";
import type { TaskPreviewLocation } from "./taskPreviewFrameHost";

export function PreviewAddressBar({
  label,
  port,
  location,
  disabled,
  onNavigate,
  onBack,
  onForward,
}: {
  label: string;
  port: number;
  location: TaskPreviewLocation;
  disabled: boolean;
  onNavigate: (input: string) => void;
  onBack: () => void;
  onForward: () => void;
}) {
  const [draft, setDraft] = useState(location.path);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(location.path);
  }, [location.path, editing]);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      <Tooltip content="Back" side="bottom">
        <Button
          size="icon-sm"
          aria-label="Back"
          data-attr="task-preview-back"
          disabled={disabled || !location.canGoBack}
          onClick={onBack}
        >
          <ArrowLeft size={14} />
        </Button>
      </Tooltip>
      <Tooltip content="Forward" side="bottom">
        <Button
          size="icon-sm"
          aria-label="Forward"
          data-attr="task-preview-forward"
          disabled={disabled || !location.canGoForward}
          onClick={onForward}
        >
          <ArrowRight size={14} />
        </Button>
      </Tooltip>
      <form
        className="min-w-0 flex-1"
        onSubmit={(event) => {
          event.preventDefault();
          onNavigate(draft);
          setEditing(false);
          (document.activeElement as HTMLElement | null)?.blur();
        }}
      >
        <InputGroup className="h-7">
          <InputGroupAddon align="inline-start">
            <span className="max-w-32 truncate text-foreground text-xs">
              {label}
            </span>
            <span className="text-muted-foreground text-xs">:{port}</span>
          </InputGroupAddon>
          <InputGroupInput
            aria-label="Page address"
            data-attr="task-preview-address"
            value={draft}
            disabled={disabled}
            spellCheck={false}
            className="text-xs"
            onChange={(event) => setDraft(event.target.value)}
            onFocus={(event) => {
              setEditing(true);
              const input = event.currentTarget;
              requestAnimationFrame(() => input.select());
            }}
            onBlur={() => setEditing(false)}
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              setDraft(location.path);
              event.currentTarget.blur();
            }}
          />
        </InputGroup>
      </form>
    </div>
  );
}
