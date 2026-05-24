import { CompatMessage } from './types'

// Heuristic mirrors the LLMA skill script `extract_conversation.py` at
// `products/llm_analytics/skills/exploring-llm-traces/scripts/` — keep in sync.

/**
 * Provider-specific transport metadata that lives on typed content parts but
 * does NOT change what the user sees. Stripped before signing so that the
 * same user-visible message dedups across turns even if the caller changes
 * its cache hint, the SDK adds a verification signature, or routing metadata
 * differs between echoes.
 *
 *   - `cache_control` — Anthropic cache hints on text parts; vary across turns.
 *   - `signature` — Anthropic crypto signature on `thinking` parts; varies between echoes.
 *   - `caller` — routing metadata on `tool_use` parts; not user-visible.
 *
 * The replacer fires recursively for every key during serialisation, so these
 * fields are dropped at any nesting level.
 */
const TRANSPORT_METADATA_KEYS = new Set(['cache_control', 'signature', 'caller'])

function isPlainTextPart(part: unknown): boolean {
    return (
        typeof part === 'object' &&
        part !== null &&
        (part as Record<string, unknown>).type === 'text' &&
        typeof (part as Record<string, unknown>).text === 'string'
    )
}

function normalizeSignatureField(key: string, value: unknown): unknown {
    if (TRANSPORT_METADATA_KEYS.has(key)) {
        return undefined
    }
    // Converge text-only typed-parts with their flat-string equivalent. SDKs
    // round-trip the same assistant reply between `content: 'Hello'` (OpenAI
    // flat-string) and `content: [{type: 'text', text: 'Hello'}]` (typed parts);
    // without this convergence the signatures diverge and the message re-renders.
    // Only flatten all-text arrays — mixed content (text + tool_use) has no
    // flat-string equivalent.
    if (key === 'content' && Array.isArray(value) && value.length > 0 && value.every(isPlainTextPart)) {
        return value.map((part) => (part as { text: string }).text).join('')
    }
    return value
}

/**
 * Stable string hash for a normalized message. Keys on role, content,
 * tool_calls, tool_call_id, and the synthetic tools list — ignoring transport
 * metadata (see `TRANSPORT_METADATA_KEYS`) and converging text-only typed-parts
 * arrays with their flat-string equivalent (see `normalizeSignatureField`).
 */
export function messageSignature(message: CompatMessage): string {
    // JSON.stringify preserves order
    return JSON.stringify(
        {
            role: message.role ?? '',
            content: message.content ?? '',
            tool_calls: message.tool_calls ?? null,
            tool_call_id: message.tool_call_id ?? '',
            tools: (message as { tools?: unknown }).tools ?? null,
        },
        // Call normalizeSignatureField for each field above:
        normalizeSignatureField
    )
}
