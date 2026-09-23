import { ChatCircle, CheckCircle, PaperPlaneTilt } from "@phosphor-icons/react";
import type { VoiceToolCall } from "@posthog/core/voice/schemas";
import { ToolRow } from "@posthog/ui/features/sessions/components/session-update/ToolRow";

export function VoiceToolActivity({
  calls,
}: {
  calls: VoiceToolCall[];
}): React.JSX.Element | null {
  if (calls.length === 0) return null;
  return (
    <section
      className="max-h-40 space-y-1 overflow-y-auto px-3 py-2"
      aria-label="Voice actions"
    >
      {calls.map((call) => (
        <ToolRow
          key={call.id}
          icon={call.name === "answer_question" ? ChatCircle : PaperPlaneTilt}
          isLoading={call.status === "running"}
          isFailed={call.status === "failed"}
          trailing={
            call.status === "completed" ? (
              <CheckCircle size={14} className="text-success" />
            ) : undefined
          }
          content={
            <div className="space-y-1 break-words text-xs">
              <p className="text-muted-foreground">{call.input}</p>
              {call.result && <p>{call.result}</p>}
              <code className="text-muted-foreground">{call.name}</code>
            </div>
          }
        >
          <span className="min-w-0 truncate text-xs">
            {call.name === "answer_question"
              ? "Answer question"
              : "Send to task"}
            {call.result && call.status === "completed"
              ? `: ${call.result}`
              : ""}
          </span>
        </ToolRow>
      ))}
    </section>
  );
}
