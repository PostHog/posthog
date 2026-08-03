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
 *   - The signed hash carries a reference to the action context through
 *     the model; the payload itself waits in Redis, which execute already
 *     depends on for single-use enforcement — any server instance sharing
 *     that Redis can serve `execute`.
 *   - The security model is weaker than client-rendered elicitation
 *     (the LLM controls the `confirmation` argument), but strictly
 *     stronger than a single destructive tool. Honest tradeoff documented
 *     in the spec.
 *
 * What each helper does:
 *
 *   - `prepareConfirmedAction()` — runs at the top of the `-prepare` tool
 *     handler. Stashes the validated args server-side and signs their
 *     SHA-256 digest + user identity into a small constant-size hash the
 *     model surfaces to the user. Args can be arbitrarily large (a scout
 *     body plus reference files, say) without bloating what the model has
 *     to relay verbatim between the two calls.
 *   - `executeConfirmedAction()` — runs at the top of the `-execute` tool
 *     handler. Verifies the hash and the literal "confirm" string, then
 *     fetches-and-burns the stashed payload (the burn is the single-use
 *     guard) and checks it against the signed digest. Returns the
 *     validated payload (the original args) for the rest of the handler
 *     to act on, or a `ToolErrorResult` to short-circuit the call.
 *
 * Failure UX note: the nonce is consumed before the underlying handler
 * runs. If the downstream API call then fails, the user must run
 * prepare + confirm again — that's intentional. A failed call may have
 * partially succeeded server-side, and silently allowing a retry under
 * the same confirmation could perform the action a second time when the
 * user thought it had been canceled.
 */

import { createHash } from 'node:crypto'

import {
    confirmedActionExecutesTotal,
    confirmedActionPreparesTotal,
    confirmedActionRefusalsTotal,
} from '@/hono/metrics'
import { ToolInputValidationError } from '@/lib/errors'
import {
    MAX_STASHED_PAYLOAD_BYTES,
    NonceLedger,
    PAYLOAD_STASH_TTL_MARGIN_SECONDS,
    PayloadStash,
    SignedStateAlreadyConsumed,
    SignedStateCodec,
    SignedStateError,
    STASH_QUOTA_BYTES_PER_WINDOW,
} from '@/lib/signed-state'

import type { Context } from './types'

/** The literal word the user must type to confirm. Fixed by design. */
export const CONFIRMATION_WORD = 'confirm'

/**
 * Marker arg names the codegen injects into `-execute` tool schemas.
 * Exported so tests and codegen reference one source of truth.
 */
export const CONFIRMATION_HASH_ARG = 'confirmation_hash'
export const CONFIRMATION_WORD_ARG = 'confirmation'

/**
 * Ambient scope (active project / organization) an action targets. Signed
 * at prepare time and re-checked at execute time so a confirmation issued
 * while one project was active can't be replayed against a different one.
 */
export type ConfirmedActionScope = Record<string, string>

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
    /** Stash the payload waits in between prepare and execute. Single instance reused across requests. */
    stash: PayloadStash
    /**
     * Ambient scope resolved from current state at prepare time (e.g. the
     * active project the action targets). Stashed with the args and
     * digest-bound into the hash; `execute` refuses if the scope active at
     * execute time no longer matches. Omit for actions with no project/org
     * scope.
     */
    boundScope?: ConfirmedActionScope
}

/**
 * Shape of the stashed payload. The runtime wraps the caller's args
 * together with the bound scope so both travel — and are digest-checked —
 * as one serialized unit.
 */
interface SignedConfirmedActionPayload {
    args: Record<string, unknown>
    scope: ConfirmedActionScope | null
}

/**
 * Shape of the `payload` claim signed into the token: a reference to the
 * stashed payload, not the payload itself. The nonce (a standard claim)
 * keys the stash entry; the digest tamper-proofs it.
 */
interface SignedPayloadReference {
    digest: string
}

function isPayloadReference(value: unknown): value is SignedPayloadReference {
    return (
        value !== null &&
        typeof value === 'object' &&
        !Array.isArray(value) &&
        typeof (value as Partial<SignedPayloadReference>).digest === 'string'
    )
}

function sha256Hex(value: string): string {
    return createHash('sha256').update(value).digest('hex')
}

export interface PrepareConfirmedActionResult {
    confirmation_hash: string
    confirmation_word: typeof CONFIRMATION_WORD
    action: string
    message: string
    /** Hint for the model. Surfaces as text on the tool result. */
    next_steps: string
}

export function isPrepareConfirmedActionResult(value: unknown): value is PrepareConfirmedActionResult {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return false
    }
    const candidate = value as Partial<PrepareConfirmedActionResult>
    return typeof candidate.confirmation_hash === 'string' && candidate.confirmation_word === CONFIRMATION_WORD
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
    const payload: SignedConfirmedActionPayload = {
        args: options.args,
        scope: options.boundScope ?? null,
    }
    // Digest the exact string that gets stashed — execute re-hashes the
    // stored string, so serialization only has to be stable across this
    // one round-trip, not canonical.
    const serialized = JSON.stringify(payload)
    const serializedBytes = Buffer.byteLength(serialized, 'utf8')
    if (serializedBytes > MAX_STASHED_PAYLOAD_BYTES) {
        confirmedActionPreparesTotal.inc({ tool: options.purpose, status: 'refused' })
        confirmedActionRefusalsTotal.inc({ tool: options.purpose, reason: 'payload_too_large' })
        throw new ToolInputValidationError(
            `${options.purpose} was not prepared: the action arguments are too large to confirm ` +
                `(${serializedBytes} bytes; limit ${MAX_STASHED_PAYLOAD_BYTES}). Trim the arguments, ` +
                `for example by shortening bundled file contents, and try again.`
        )
    }
    const stashWindowSeconds = options.codec.ttlSeconds + PAYLOAD_STASH_TTL_MARGIN_SECONDS
    const quotaTotal = await options.stash.charge(sub, serializedBytes, stashWindowSeconds)
    if (quotaTotal > STASH_QUOTA_BYTES_PER_WINDOW) {
        await options.stash.repairQuotaExpiry(sub, stashWindowSeconds)
        confirmedActionPreparesTotal.inc({ tool: options.purpose, status: 'refused' })
        confirmedActionRefusalsTotal.inc({ tool: options.purpose, reason: 'stash_quota_exceeded' })
        throw new ToolInputValidationError(
            `${options.purpose} was not prepared: too much pending confirmation data for this user ` +
                `(${quotaTotal} bytes in the current window; limit ${STASH_QUOTA_BYTES_PER_WINDOW}). ` +
                `Wait a few minutes for pending confirmations to expire and try again.`
        )
    }
    const reference: SignedPayloadReference = { digest: sha256Hex(serialized) }
    const { token, claims } = await options.codec.encode({
        sub,
        purpose: options.purpose,
        payload: reference,
    })
    await options.stash.put(claims.nonce, serialized, options.codec.ttlSeconds + PAYLOAD_STASH_TTL_MARGIN_SECONDS)
    confirmedActionPreparesTotal.inc({ tool: options.purpose, status: 'ok' })
    return {
        confirmation_hash: token,
        confirmation_word: CONFIRMATION_WORD,
        action: options.actionLabel,
        message: interpolate(options.messageTemplate, options.args),
        next_steps:
            `Surface the message above to the user. Wait for them to reply with the literal word "${CONFIRMATION_WORD}". ` +
            `Then call the matching \`-execute\` tool with \`${CONFIRMATION_HASH_ARG}\` set to the confirmation_hash from this result, ` +
            `and \`${CONFIRMATION_WORD_ARG}\` set to the user's literal reply. The signed hash already contains the action arguments. ` +
            `If the user does not reply with "${CONFIRMATION_WORD}", do not call the execute tool. ` +
            `The confirmation expires ${Math.round(options.codec.ttlSeconds / 60)} minutes after this call. ` +
            `If the user confirms later than that, call this prepare tool again with the same arguments to get a fresh hash.`,
    }
}

export interface ExecuteConfirmedActionOptions {
    /** The execute tool accepts only the signed hash and the user's confirmation word. */
    incomingArgs: { [CONFIRMATION_HASH_ARG]: string; [CONFIRMATION_WORD_ARG]: string }
    /** Same `purpose` value used at prepare time. */
    purpose: string
    /** Codec + stash + ledger; all single instances reused across requests. */
    codec: SignedStateCodec
    stash: PayloadStash
    /** Single-use guard for inline-payload tokens only; stash-referenced tokens burn via `take()`. */
    ledger: NonceLedger
    /**
     * Scope resolved from *current* state at execute time. Compared against
     * the scope signed at prepare time; any mismatch refuses. Omit for
     * actions prepared without a `boundScope`.
     */
    expectedScope?: ConfirmedActionScope
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
    options: ExecuteConfirmedActionOptions
): Promise<ExecuteConfirmedActionOutcome<P>> {
    const sub = await context.getDistinctId()

    const hash = options.incomingArgs[CONFIRMATION_HASH_ARG]
    const word = options.incomingArgs[CONFIRMATION_WORD_ARG]

    if (typeof word !== 'string' || word !== CONFIRMATION_WORD) {
        return refuse(
            options.purpose,
            'wrong_word',
            `${options.purpose} was not executed: the \`${CONFIRMATION_WORD_ARG}\` argument must be the literal string "${CONFIRMATION_WORD}", typed by the user. The user did not confirm.`
        )
    }

    let claims
    try {
        claims = await options.codec.decode(hash, sub, options.purpose)
    } catch (err) {
        if (err instanceof SignedStateError) {
            return refuse(options.purpose, err.kind, `${options.purpose} was not executed: ${reasonFor(err)}.`)
        }
        throw err
    }

    let wrapper: Partial<SignedConfirmedActionPayload>
    if (isPayloadReference(claims.payload)) {
        // Stash-referenced token: the burn inside `take()` IS the
        // single-use enforcement — a second execute (or a lost DEL race)
        // gets `null` here.
        const stored = await options.stash.take(claims.nonce)
        if (stored === null) {
            return refuse(
                options.purpose,
                'replay',
                `${options.purpose} was not executed: this confirmation has already been used or its prepared payload has expired. Start a new prepare-then-execute cycle if you need to perform the action again.`
            )
        }
        if (sha256Hex(stored) !== claims.payload.digest) {
            return refuse(
                options.purpose,
                'digest_mismatch',
                `${options.purpose} was not executed: the stored confirmation payload does not match the signed digest. Run the prepare step again.`
            )
        }
        let parsed: unknown
        try {
            parsed = JSON.parse(stored)
        } catch {
            parsed = null
        }
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return refuse(
                options.purpose,
                'malformed_payload',
                `${options.purpose} was not executed: confirmation payload is malformed.`
            )
        }
        wrapper = parsed as Partial<SignedConfirmedActionPayload>
    } else {
        // Inline-payload token — args signed directly into the claim
        // instead of stashed. Minted by servers on the older token format;
        // honored so a confirmation spanning a mixed-version deploy still
        // executes. Here the ledger supplies the single-use guarantee that
        // `take()` gives the stash path, with its TTL bound to the token's
        // remaining life (per the codec's clock, not the wall clock — drift
        // between signer and consumer could otherwise shrink the ledger TTL
        // enough to re-allow replay).
        try {
            await options.ledger.consume(claims.nonce, options.codec.secondsUntilExpiry(claims))
        } catch (err) {
            if (err instanceof SignedStateAlreadyConsumed) {
                return refuse(
                    options.purpose,
                    'replay',
                    `${options.purpose} was not executed: this confirmation has already been used. Start a new prepare-then-execute cycle if you need to perform the action again.`
                )
            }
            throw err
        }
        const verified = claims.payload
        if (verified === null || typeof verified !== 'object' || Array.isArray(verified)) {
            return refuse(
                options.purpose,
                'malformed_payload',
                `${options.purpose} was not executed: confirmation payload is malformed.`
            )
        }
        wrapper = verified as Partial<SignedConfirmedActionPayload>
    }

    // Whichever path produced the wrapper, treat it as untrusted JSON and
    // shape-check the args object it carries before returning.
    const args = wrapper.args
    if (args === null || typeof args !== 'object' || Array.isArray(args)) {
        return refuse(
            options.purpose,
            'malformed_payload',
            `${options.purpose} was not executed: confirmation payload is malformed.`
        )
    }

    // Scope binding: the project/org that was active at prepare time is
    // signed into the token. If the active scope has since changed (e.g. the
    // agent ran `switch-project` after the user confirmed), the same
    // confirmation must not authorize the action against a different target.
    if (!scopesMatch(wrapper.scope ?? null, options.expectedScope ?? null)) {
        return refuse(
            options.purpose,
            'scope_mismatch',
            `${options.purpose} was not executed: the confirmation was issued for a different project or organization than the one currently active. Switch back to the project the action was prepared in, or run the prepare step again in the current one.`
        )
    }

    confirmedActionExecutesTotal.inc({ tool: options.purpose, status: 'ok' })
    return { ok: true, verifiedArgs: args as P }
}

/**
 * Compare the scope signed at prepare time against the scope active at
 * execute time. Both are shallow string maps (or `null` when the action is
 * unscoped). A mismatch on any key — or a differing key set — fails closed.
 */
function scopesMatch(signed: ConfirmedActionScope | null, expected: ConfirmedActionScope | null): boolean {
    const a = signed ?? {}
    const b = expected ?? {}
    const keys = new Set([...Object.keys(a), ...Object.keys(b)])
    for (const key of keys) {
        if (a[key] !== b[key]) {
            return false
        }
    }
    return true
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
