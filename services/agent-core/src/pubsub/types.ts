/**
 * Per-session event types. Best-effort delivery over the bus; the durable record
 * is the queue row and the final state blob.
 */
export type SessionEvent =
    | { type: 'turn_started'; at: string }
    | { type: 'turn_completed'; at: string }
    | { type: 'tool_call'; tool: string; at: string; args?: unknown }
    | { type: 'tool_result'; tool: string; at: string; ok: boolean; result?: unknown; error?: string }
    | { type: 'message'; at: string; role: 'assistant' | 'system' | 'user'; content: string }
    /**
     * Ephemeral token chunk of the assistant's in-flight reply. Streamed to live
     * SSE listeners for a token-by-token reveal, but NEVER persisted — the
     * session-logger drops it (a streamed answer is hundreds of these). The
     * durable record stays the final complete `message`.
     */
    | { type: 'message_delta'; at: string; text: string }
    /** One-line user-visible progress update from the agent's `notify_user` meta tool. */
    | { type: 'status'; at: string; text: string }
    /** Agent has suspended via `ask_for_input` and is waiting for a `/send/:id` message. */
    | { type: 'awaiting_input'; at: string; prompt: string | null }
    | { type: 'session_completed'; at: string; output: unknown }
    | { type: 'session_failed'; at: string; error: string }

/**
 * Messages sent in on a session's input channel.
 *  - `user_message` — a `/send/:id` turn, picked up by the runner at the next yield.
 *  - `cancel` — a `/cancel/:id` request; the runner aborts the in-flight run.
 */
export type SessionInputMessage = { type: 'user_message'; at: string; content: string } | { type: 'cancel'; at: string }

export type SessionEventListener = (event: SessionEvent) => void
export type SessionInputListener = (message: SessionInputMessage) => void

export interface SessionBus {
    /** Publish an event for a session. Returns when at least one subscriber has been notified (best-effort). */
    publishEvent(sessionId: string, event: SessionEvent): Promise<void>

    /** Subscribe to the session's event channel. Returns an unsubscribe function. */
    subscribeEvents(sessionId: string, listener: SessionEventListener): Promise<() => Promise<void>>

    /** Publish a user-input message for a session. */
    publishInput(sessionId: string, message: SessionInputMessage): Promise<void>

    /** Subscribe to the session's input channel (runner side). */
    subscribeInput(sessionId: string, listener: SessionInputListener): Promise<() => Promise<void>>

    disconnect(): Promise<void>
}
