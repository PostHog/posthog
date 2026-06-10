/**
 * Runtime for the typed-confirm two-tool paradigm.
 *
 * For destructive or security-sensitive tools, codegen emits TWO tools per
 * YAML entry: `<name>-prepare` and `<name>-execute`. The model calls them in
 * sequence; the user is expected to type the literal word "confirm" in
 * chat between the two calls.
 *
 * Why two tools and not elicitation:
 *
 *   - Works on every MCP client today (no protocol-level elicitation
 *     dependency).
 *   - Stateless: the signed hash carries the action context through the
 *     model — any server instance can serve `execute`.
 *   - The security model is weaker than client-rendered elicitation
 *     (the LLM controls the `confirmation` argument), but strictly
 *     stronger than a single destructive tool. Honest tradeoff documented
 *     in the spec.
 *
 * What each helper does:
 *
 *   - `prepareConfirmedAction()` — runs at the top of the `-prepare` tool
 *     handler. Signs the validated args + user identity into a hash and
 *     returns a result the model surfaces to the user.
 *   - `executeConfirmedAction()` — runs at the top of the `-execute` tool
 *     handler. Verifies the hash, the literal "confirm" string, and the
 *     single-use nonce ledger. Returns the validated payload (the original
 *     args) for the rest of the handler to act on, or a `ToolErrorResult`
 *     to short-circuit the call.
 *
 * Failure UX note: the nonce is consumed before the underlying handler
 * runs. If the downstream API call then fails, the user must run
 * prepare + confirm again — that's intentional. A failed call may have
 * partially succeeded server-side, and silently allowing a retry under
 * the same confirmation could perform the action a second time when the
 * user thought it had been canceled.
 */

import {
    confirmedActionExecutesTotal,
    confirmedActionPreparesTotal,
    confirmedActionRefusalsTotal,
} from '@/hono/metrics'
import { NonceLedger, SignedStateAlreadyConsumed, SignedStateCodec, SignedStateError } from '@/lib/signed-state'

import type { Context } from './types'

/** The literal word the user must type to confirm. Fixed by design. */
export const CONFIRMATION_WORD = 'confirm'

/**
 * Marker arg names the codegen injects into `-execute` tool schemas.
 * Exported so tests and codegen reference one source of truth.
 */
export const CONFIRMATION_HASH_ARG = 'confirmation_hash'
export const CONFIRMATION_WORD_ARG = 'confirmation'

export interface PrepareConfirmedActionOptions<P extends Record<string, unknown>> {
    /** The validated tool args. Signed into the hash so they can't be tampered with between prepare and execute. */
    args: P
    /**
     * Stable identifier for the logical action — typically the underlying
     * tool name (NOT the `-prepare`/`-execute` suffix). Bound into the hash
     * so a hash issued for action A can't be used to authorize action B.
     */
    purpose: string
    /** Human-readable label surfaced to the user. */
    actionLabel: string
    /** Prompt template shown to the user. Supports `{paramName}` interpolation from `args`. */
    messageTemplate: string
    /** Codec — instantiated once at startup, reused across requests. */
    codec: SignedStateCodec
}

export interface PrepareConfirmedActionResult {
    confirmation_hash: string
    confirmation_word: typeof CONFIRMATION_WORD
    action: string
    message: string
    /** Hint for the model. Surfaces as text on the tool result. */
    next_steps: string
}

/**
 * Run at the top of a `-prepare` tool's handler. Signs the args into a
 * hash and returns the payload the model relays to the user.
 */
export async function prepareConfirmedAction<P extends Record<string, unknown>>(
    context: Context,
    options: PrepareConfirmedActionOptions<P>
): Promise<PrepareConfirmedActionResult> {
    const sub = await context.getDistinctId()
    const { token } = await options.codec.encode({
        sub,
        purpose: options.purpose,
        payload: options.args,
    })
    confirmedActionPreparesTotal.inc({ tool: options.purpose, status: 'ok' })
    return {
        confirmation_hash: token,
        confirmation_word: CONFIRMATION_WORD,
        action: options.actionLabel,
        message: interpolate(options.messageTemplate, options.args),
        next_steps:
            `Surface the message above to the user. Wait for them to reply with the literal word "${CONFIRMATION_WORD}". ` +
            `Then call the matching \`-execute\` tool with \`${CONFIRMATION_HASH_ARG}\` set to the confirmation_hash from this result, ` +
            `\`${CONFIRMATION_WORD_ARG}\` set to the user's literal reply, and the same arguments you used here. ` +
            `If the user does not reply with "${CONFIRMATION_WORD}", do not call the execute tool.`,
    }
}

export interface ExecuteConfirmedActionOptions<P extends Record<string, unknown>> {
    /** The full incoming args object — includes `confirmation_hash`, `confirmation`, and the original tool args. */
    incomingArgs: P & { [CONFIRMATION_HASH_ARG]: string; [CONFIRMATION_WORD_ARG]: string }
    /** Same `purpose` value used at prepare time. */
    purpose: string
    /** Codec + ledger; both single instances reused across requests. */
    codec: SignedStateCodec
    ledger: NonceLedger
}

export type ExecuteConfirmedActionOutcome<P> = { ok: true; verifiedArgs: P } | { ok: false; result: ToolErrorResult }

interface ToolErrorResult {
    content: Array<{ type: 'text'; text: string }>
    isError: true
}

/**
 * Run at the top of an `-execute` tool's handler. Verifies the hash, the
 * confirmation string, and burns the nonce. Returns the validated args
 * (without the framework fields) on success, or a `ToolErrorResult` to
 * short-circuit.
 */
export async function executeConfirmedAction<P extends Record<string, unknown>>(
    context: Context,
    options: ExecuteConfirmedActionOptions<P>
): Promise<ExecuteConfirmedActionOutcome<P>> {
    const sub = await context.getDistinctId()

    const hash = options.incomingArgs[CONFIRMATION_HASH_ARG]
    const word = options.incomingArgs[CONFIRMATION_WORD_ARG]

    if (typeof word !== 'string' || word !== CONFIRMATION_WORD) {
        return refuse(
            options.purpose,
            'wrong_word',
            `${options.purpose} was not executed — the \`${CONFIRMATION_WORD_ARG}\` argument must be the literal string "${CONFIRMATION_WORD}", typed by the user. The user did not confirm.`
        )
    }

    let claims
    try {
        claims = await options.codec.decode(hash, sub, options.purpose)
    } catch (err) {
        if (err instanceof SignedStateError) {
            return refuse(options.purpose, err.kind, `${options.purpose} was not executed — ${reasonFor(err)}.`)
        }
        throw err
    }

    // Single-use enforcement. Bind the ledger TTL to the token's remaining
    // life so abandoned nonces self-clean exactly when the token they
    // protect can no longer be replayed. The remaining TTL comes from the
    // codec's clock, not the wall clock — clock drift between the signer
    // and the consumer could otherwise shrink the ledger TTL enough to
    // re-allow replay.
    try {
        await options.ledger.consume(claims.nonce, options.codec.secondsUntilExpiry(claims))
    } catch (err) {
        if (err instanceof SignedStateAlreadyConsumed) {
            return refuse(
                options.purpose,
                'replay',
                `${options.purpose} was not executed — this confirmation has already been used. Start a new prepare-then-execute cycle if you need to perform the action again.`
            )
        }
        throw err
    }

    // The payload was signed at prepare time; treat it as untrusted JSON
    // and shape-check before returning. The caller already knows the
    // expected shape via its tool schema.
    const verified = claims.payload
    if (verified === null || typeof verified !== 'object' || Array.isArray(verified)) {
        return refuse(
            options.purpose,
            'malformed_payload',
            `${options.purpose} was not executed — confirmation payload is malformed.`
        )
    }

    confirmedActionExecutesTotal.inc({ tool: options.purpose, status: 'ok' })
    return { ok: true, verifiedArgs: verified as P }
}

function refuse(purpose: string, reason: string, message: string): { ok: false; result: ToolErrorResult } {
    confirmedActionExecutesTotal.inc({ tool: purpose, status: 'refused' })
    confirmedActionRefusalsTotal.inc({ tool: purpose, reason })
    return {
        ok: false,
        result: {
            content: [{ type: 'text', text: message }],
            isError: true,
        },
    }
}

/**
 * Replace `{paramName}` placeholders in `template` with `args[paramName]`.
 * Missing keys stay as the literal `{name}` so authors notice during smoke
 * tests rather than silently shipping `"Delete organization ?"` to a user.
 * Non-scalar values (objects, arrays) are left as the literal `{name}` too
 * — these are user-facing confirmation prompts; rendering "[object Object]"
 * silently is worse than the author seeing the placeholder leak through.
 */
function interpolate(template: string, args: Record<string, unknown>): string {
    return template.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (full, key: string) => {
        if (!(key in args)) {
            return full
        }
        const value = args[key]
        const t = typeof value
        if (t === 'string' || t === 'number' || t === 'boolean') {
            return String(value)
        }
        return full
    })
}

function reasonFor(err: SignedStateError): string {
    switch (err.kind) {
        case 'expired':
            return 'the confirmation expired; please run the prepare step again'
        case 'user_mismatch':
            return 'the confirmation was issued for a different user'
        case 'purpose_mismatch':
            return 'the confirmation was issued for a different action'
        case 'bad_signature':
            return 'the confirmation signature is invalid'
        case 'malformed':
            return 'the confirmation token is malformed'
        default:
            return 'the confirmation token was rejected'
    }
}
