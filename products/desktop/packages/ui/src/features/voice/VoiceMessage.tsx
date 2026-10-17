import { Waveform } from "@phosphor-icons/react";
import type { VoiceTranscriptTurn } from "@posthog/core/voice/conversationTranscript";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@posthog/quill";
import { useState } from "react";

export function VoiceMessage({
  turns,
}: {
  turns: VoiceTranscriptTurn[];
}): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const latestRequest = turns.findLast((turn) => turn.speaker === "user");
  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} className="min-w-0">
      <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground text-xs">
        <span className="flex items-center gap-1">
          <Waveform size={12} aria-hidden="true" />
          Voice message
        </span>
        <CollapsibleTrigger className="h-auto w-auto p-0 text-xs hover:text-foreground">
          {expanded ? "Hide transcript" : "Show transcript"}
        </CollapsibleTrigger>
      </div>
      {!expanded && (
        <p className="m-0 line-clamp-4 whitespace-pre-wrap break-words">
          {latestRequest?.text}
        </p>
      )}
      <CollapsibleContent className="space-y-3 border-border border-l pl-3">
        {turns.map((turn) => (
          <div key={turn.offset}>
            <div className="mb-0.5 font-medium text-muted-foreground text-xs">
              {turn.speaker === "user" ? "You" : "Voice"}
            </div>
            <p className="m-0 whitespace-pre-wrap break-words">{turn.text}</p>
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}
