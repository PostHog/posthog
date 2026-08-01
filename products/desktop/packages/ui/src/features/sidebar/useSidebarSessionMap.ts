import { computeSidebarSessionSignature } from "@posthog/core/sidebar/buildSidebarData";
import type { AgentSession } from "@posthog/shared";
import { useMemo } from "react";
import { useSessionStore } from "../sessions/sessionStore";

/**
 * `taskId → session` map for the sidebar, rebuilt only when a sidebar-relevant
 * session field changes — not on every streamed event. The equality function
 * compares just the fields {@link computeSidebarSessionSignature} covers, so the
 * subscription (and the root-mounted sidebar) ignores the appends that fire on
 * every token during a turn.
 */
export function useSidebarSessionMap(): Map<string, AgentSession> {
  const sessions = useSessionStore(
    (s) => s.sessions,
    (a, b) =>
      computeSidebarSessionSignature(a) === computeSidebarSessionSignature(b),
  );

  return useMemo(() => {
    const map = new Map<string, AgentSession>();
    for (const session of Object.values(sessions)) {
      if (session.taskId) map.set(session.taskId, session);
    }
    return map;
  }, [sessions]);
}
