import type { SessionActivityEvent } from "@posthog/core/sessions/sessionActivity";
import { voiceConversationContext } from "@posthog/core/voice/conversationContext";
import {
  VOICE_SESSION_FACTORY,
  type VoiceSessionFactory,
} from "@posthog/core/voice/conversationVoiceSession";
import type { VoiceState, VoiceToolCall } from "@posthog/core/voice/schemas";
import type { VoiceQuestion } from "@posthog/core/voice/voiceQuestion";
import { useServiceOptional } from "@posthog/di/react";
import type { VoiceAudioLevels } from "@posthog/platform/speech";
import {
  type AgentConversationEvent,
  ANALYTICS_EVENTS,
  VOICE_CONVERSATION_FLAG,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useQuestionDraftStore } from "@posthog/ui/features/permissions/questionDraftStore";
import { track } from "@posthog/ui/shell/analytics";
import { posthogAnalyticsService } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { VoiceControls } from "./VoiceControls";
import { VoiceToolActivity } from "./VoiceToolActivity";

interface VoiceConversationProps {
  taskId?: string;
  question?: VoiceQuestion | null;
  onAnswerQuestion?(
    id: string,
    answers: Record<string, string>,
  ): Promise<boolean>;
  render?(
    controls: React.ReactNode,
    activity: React.ReactNode,
  ): React.JSX.Element;
  events: readonly (SessionActivityEvent | AgentConversationEvent)[];
  pending: boolean;
  onSend(text: string): Promise<boolean>;
  disabled?: boolean;
  active?: boolean;
}

function ActiveVoiceConversation({
  factory,
  client,
  ...props
}: VoiceConversationProps & {
  taskId: string;
  factory: VoiceSessionFactory;
  client: NonNullable<ReturnType<typeof useOptionalAuthenticatedClient>>;
}): React.JSX.Element {
  const [state, setState] = useState<VoiceState>("idle");
  const [toolCalls, setToolCalls] = useState<VoiceToolCall[]>([]);
  const [levels, setLevels] = useState<VoiceAudioLevels>({
    input: 0,
    output: 0,
  });
  const questionDraft = useQuestionDraftStore((store) =>
    props.question ? store.drafts.get(props.question.toolCallId) : undefined,
  );
  const latest = useRef(props);
  useLayoutEffect(() => {
    latest.current = props;
  });
  const session = useMemo(
    () =>
      factory({
        createSession: (sdp, signal) =>
          client.createTaskVoiceSession(
            props.taskId,
            sdp,
            voiceConversationContext(latest.current.events).context,
            signal,
          ),
        sendMessage: (text) =>
          latest.current.disabled
            ? Promise.resolve(false)
            : latest.current.onSend(text),
        answerQuestion: (id, answers) =>
          latest.current.disabled
            ? Promise.resolve(false)
            : (latest.current.onAnswerQuestion?.(id, answers) ??
              Promise.resolve(false)),
        onQuestionAnswer: (answer) => {
          const draft = useQuestionDraftStore.getState();
          draft.setStepAnswer(answer.toolCallId, answer.questionIndex, {
            selectedIds: answer.selectedIds,
            customInput: answer.customInput,
          });
          draft.setActiveStep(answer.toolCallId, answer.nextIndex);
        },
        onToolCall: (call) =>
          setToolCalls((calls) => {
            const index = calls.findIndex((item) => item.id === call.id);
            return index === -1
              ? [...calls, call].slice(-6)
              : calls.map((item) => (item.id === call.id ? call : item));
          }),
        onAudioLevels: setLevels,
        onState: (next) => {
          if (next !== "connected") setLevels({ input: 0, output: 0 });
          setState(next);
          if (next === "connected")
            track(ANALYTICS_EVENTS.VOICE_CONVERSATION_STARTED, {
              task_id: props.taskId,
            });
        },
        onEnded: ({ sessionId, seconds, finalized, failed }) => {
          track(ANALYTICS_EVENTS.VOICE_CONVERSATION_ENDED, {
            task_id: props.taskId,
            voice_duration_seconds: seconds,
            finalized,
            failed,
          });
          if (sessionId)
            posthogAnalyticsService.track("$ai_generation", {
              $ai_model: "gpt-live-1",
              $ai_provider: "openai",
              $ai_session_id: props.taskId,
              $ai_trace_id: sessionId,
              $ai_span_id: sessionId,
              $ai_stream: true,
              $ai_is_error: failed,
              ...(seconds === null ? {} : { voice_duration_seconds: seconds }),
              voice_usage_finalized: finalized,
            });
        },
      }),
    [factory, client, props.taskId],
  );

  useLayoutEffect(() => {
    session.updateQuestion(props.question ?? null, questionDraft);
  }, [session, props.question, questionDraft]);
  useEffect(() => {
    const { reply, replyKey } = voiceConversationContext(props.events);
    session.updateReply(reply, !props.pending, replyKey);
  }, [session, props.events, props.pending]);
  useEffect(() => {
    if (props.active === false) session.stop();
  }, [session, props.active]);
  useEffect(() => {
    const stop = (): void => session.stop();
    const onVisibilityChange = (): void => {
      if (document.hidden) stop();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("pagehide", stop);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("pagehide", stop);
      stop();
    };
  }, [session]);
  const controls = (
    <VoiceControls
      state={state}
      levels={levels}
      disabled={props.disabled || props.active === false}
      onStart={() => void session.start()}
      onStop={() => session.stop()}
    />
  );
  return props.render
    ? props.render(controls, <VoiceToolActivity calls={toolCalls} />)
    : controls;
}

export function VoiceConversationControl(
  props: VoiceConversationProps,
): React.JSX.Element | null {
  const factory = useServiceOptional<VoiceSessionFactory>(
    VOICE_SESSION_FACTORY,
  );
  const enabled = useFeatureFlag(VOICE_CONVERSATION_FLAG);
  const client = useOptionalAuthenticatedClient();
  const { data: user } = useCurrentUser({
    client,
    enabled: !!factory && enabled,
  });
  return props.taskId &&
    factory &&
    client &&
    enabled &&
    user?.is_staff === true ? (
    <ActiveVoiceConversation
      key={props.taskId}
      factory={factory}
      client={client}
      {...props}
      taskId={props.taskId}
    />
  ) : props.render ? (
    props.render(null, null)
  ) : null;
}
