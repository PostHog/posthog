import { Microphone, PhoneDisconnect } from "@phosphor-icons/react";
import type { VoiceState } from "@posthog/core/voice/schemas";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";

export function VoiceControls({
  state,
  disabled = false,
  onStart,
  onStop,
}: {
  state: VoiceState;
  disabled?: boolean;
  onStart(): void;
  onStop(): void;
}): React.JSX.Element {
  const active =
    state === "connecting" || state === "connected" || state === "closing";
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              size="sm"
              variant={active ? "outline" : "default"}
              disabled={state === "closing" || (!active && disabled)}
              onClick={active ? onStop : onStart}
              aria-label={
                state === "connecting" ? "Cancel voice connection" : undefined
              }
            />
          }
        >
          {state === "connecting" || state === "closing" ? (
            <Spinner aria-hidden="true" />
          ) : active ? (
            <PhoneDisconnect />
          ) : (
            <Microphone />
          )}
          {state === "connecting"
            ? "Connecting…"
            : state === "closing"
              ? "Ending…"
              : active
                ? "End voice"
                : "Start voice"}
        </TooltipTrigger>
        <TooltipContent>
          {active
            ? "End voice. The task will continue."
            : "Audio and recent conversation text are sent to OpenAI."}
        </TooltipContent>
      </Tooltip>
      {state === "connected" && (
        <output className="text-muted-foreground text-xs">Microphone on</output>
      )}
      {state === "error" && (
        <span className="max-w-64 text-destructive text-xs" role="alert">
          Voice could not connect. Check microphone access and try again.
        </span>
      )}
    </div>
  );
}
