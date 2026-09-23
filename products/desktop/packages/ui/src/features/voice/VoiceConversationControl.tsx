import type { SessionActivityEvent } from "@posthog/core/sessions/sessionActivity";
import { voiceConversationContext } from "@posthog/core/voice/conversationContext";
import {
  VOICE_SESSION_FACTORY,
  type VoiceSessionFactory,
} from "@posthog/core/voice/conversationVoiceSession";
import type { VoiceState } from "@posthog/core/voice/schemas";
import { useServiceOptional } from "@posthog/di/react";
import {
  type AgentConversationEvent,
  ANALYTICS_EVENTS,
  VOICE_CONVERSATION_FLAG,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { track } from "@posthog/ui/shell/analytics";
import { posthogAnalyticsService } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useEffect, useMemo, useRef, useState } from "react";
import { VoiceControls } from "./VoiceControls";

interface VoiceConversationProps {
  taskId: string;
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
  factory: VoiceSessionFactory;
  client: NonNullable<ReturnType<typeof useOptionalAuthenticatedClient>>;
}): React.JSX.Element {
  const [state, setState] = useState<VoiceState>("idle");
  const latest = useRef(props);
  latest.current = props;
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
        onState: (next) => {
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
  return (
    <VoiceControls
      state={state}
      disabled={props.disabled || props.active === false}
      onStart={() => void session.start()}
      onStop={() => session.stop()}
    />
  );
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
  return factory && client && enabled && user?.is_staff === true ? (
    <ActiveVoiceConversation
      key={props.taskId}
      factory={factory}
      client={client}
      {...props}
    />
  ) : null;
}
