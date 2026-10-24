import { WarningCircle, Waveform } from "@phosphor-icons/react";
import {
  isVoiceErrorState,
  type VoiceErrorState,
  type VoiceState,
} from "@posthog/core/voice/schemas";
import type { VoiceAudioLevels } from "@posthog/platform/speech";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { VoiceActivity } from "./VoiceActivity";

const errorMessages: Record<VoiceErrorState, string> = {
  "microphone-error":
    "Microphone unavailable. Check microphone access and try again.",
  "service-error":
    "Voice service could not connect. Use the text box or try again later.",
  error: "Voice could not connect. Check your connection and try again.",
};

export function VoiceControls({
  state,
  levels = { input: 0, output: 0 },
  disabled = false,
  onStart,
  onStop,
}: {
  state: VoiceState;
  levels?: VoiceAudioLevels;
  disabled?: boolean;
  onStart(): void;
  onStop(): void;
}): React.JSX.Element {
  const active =
    state === "connecting" || state === "connected" || state === "closing";
  const error = isVoiceErrorState(state) ? errorMessages[state] : null;
  const label =
    state === "connecting"
      ? "Cancel voice connection"
      : active
        ? "End voice"
        : "Start voice";
  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              size="icon"
              variant={active ? "outline" : "default"}
              className={
                error
                  ? "text-destructive"
                  : active
                    ? "text-primary"
                    : "text-muted-foreground"
              }
              disabled={state === "closing" || (!active && disabled)}
              onClick={active ? onStop : onStart}
              aria-label={label}
              aria-pressed={active}
              data-attr="voice-conversation-toggle"
            />
          }
        >
          {state === "connecting" || state === "closing" ? (
            <Spinner aria-hidden="true" />
          ) : state === "connected" ? (
            <VoiceActivity levels={levels} />
          ) : error ? (
            <WarningCircle size={16} />
          ) : (
            <Waveform size={16} />
          )}
        </TooltipTrigger>
        <TooltipContent className="max-w-64">
          {error ??
            (active
              ? "End voice. The task will continue."
              : "Start voice. Audio and recent conversation text are sent to OpenAI.")}
        </TooltipContent>
      </Tooltip>
      {state === "connected" && (
        <output className="sr-only">Microphone on</output>
      )}
      {error && (
        <span className="sr-only" role="alert">
          {error}
        </span>
      )}
    </>
  );
}
