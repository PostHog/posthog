/**
 * Body / query schemas for the chat trigger.
 *
 * Living source of truth: this file. The HTTP handlers `safeParse` against
 * these schemas at the trigger edge (so silent coercion of bad payloads to
 * empty strings can't happen), and `chatTriggerJsonSchemas` exposes the same
 * shapes via `GET /agents/<slug>/schemas` so callers can discover the
 * contract without grepping this file.
 */

import { z } from 'zod'

export const ChatRunBodySchema = z.object({
    message: z.string().min(1, 'message must be a non-empty string'),
    external_key: z.string().optional(),
})

export const ChatSendBodySchema = z.object({
    session_id: z.string().uuid('session_id must be a UUID'),
    message: z.string().min(1, 'message must be a non-empty string'),
})

export const ChatCancelBodySchema = z.object({
    session_id: z.string().uuid('session_id must be a UUID'),
})

export const ChatListenQuerySchema = z.object({
    session_id: z.string().uuid('session_id must be a UUID'),
})

/**
 * Trigger-wide JSON Schema map served by the agent-level `/schemas` endpoint.
 * Computed once at module load — the zod schemas are static.
 */
export const chatTriggerJsonSchemas = {
    run: { body: z.toJSONSchema(ChatRunBodySchema) },
    send: { body: z.toJSONSchema(ChatSendBodySchema) },
    cancel: { body: z.toJSONSchema(ChatCancelBodySchema) },
    listen: { query: z.toJSONSchema(ChatListenQuerySchema) },
}
