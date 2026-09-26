/**
 * Removes credential-shaped text from the error values of an LLM trace before
 * they reach an MCP client.
 *
 * `$ai_error` and `$ai_error_normalized` are part of the AI payload an agent asks
 * for, so the trace allowlist retains them. Their text is written by the provider
 * or by the calling framework though, and neither treats it as a public field: a
 * provider that rejects a key quotes the key back in the message, and a framework
 * that wraps the failure attaches the request headers next to it. The provider
 * masks the middle of the key it quotes, which still leaves the prefix and the
 * last characters, and a masked key is credential material.
 *
 * So a rule on the property name cannot make these two fields safe, and the value
 * needs a pass of its own. Matching on credential shapes needs no access to the
 * live secrets, which this boundary does not have.
 *
 * The prompts and the outputs are out of scope, although an application can paste
 * a key into one. They are the payload these tools exist to return, and the rules
 * below would rewrite any legitimate `password:` or `token` text in a
 * conversation, which spends the common case to defend a rare one. An error value
 * is also short, where a prompt body is the payload `trace-compaction.ts` exists
 * to bound.
 *
 * This is a client-boundary safeguard, like the allowlist beside it. The stored
 * event and the PostHog UI keep the complete error text.
 *
 * Other trees hold their own credential prefix lists, in another language or
 * another package, and none of them is importable here. No list is the canonical
 * one.
 */

import { assignKey, isRecord } from '@/lib/plain-object'

const REDACTED = '[redacted]'

/**
 * Characters a provider uses to mask the middle of a key. They belong in a
 * credential body as much as the alphanumerics do, because `sk-ab****cd` is one
 * token rather than a token beside punctuation, and a rule that stops at the
 * first asterisk returns the readable half of the key.
 */
const MASK = '*•·#'

const BODY = `[A-Za-z0-9_${MASK}-]`

/**
 * A credential body. The dots of an elided middle (`sk-ab...cd`) count as body
 * only between two runs of body characters, because a trailing dot is sentence
 * punctuation and swallowing it joins the redaction to the next word.
 */
const CREDENTIAL_BODY = `${BODY}{6,}(?:[.…]+${BODY}+)*`

/**
 * Prefixes the LLM providers, the cloud vendors, GitHub, Slack and PostHog give
 * their credentials. The two public prefixes of the same families are left out on
 * purpose: Stripe's `pk_` publishable key and PostHog's own `phc_` project token
 * are meant to ship inside a client.
 */
const CREDENTIAL_PREFIX =
    '(?:(?:sk|rk|xai|xox[abprs])[-_]|(?:gsk|hf|r8|gh[psour]|github_pat|ph[aersx])_|AKIA|ASIA|AIza)'

const PREFIXED_CREDENTIAL = new RegExp(`\\b${CREDENTIAL_PREFIX}${CREDENTIAL_BODY}`, 'g')

/** An `Authorization` header value, whose token carries no prefix of its own. */
const AUTH_SCHEME_CREDENTIAL = new RegExp(`\\b(?:bearer|basic)\\s+[A-Za-z0-9._~+/=${MASK}-]{8,}`, 'gi')

/** The words that name a credential, in a message and as a key of a payload. */
const SECRET_WORD =
    '(?:(?:api|access|secret|client|subscription)[-_ ]?(?:key|secret|token)|(?:access|refresh|auth|session)[-_]?token|authorization|credentials?|secret|password|passwd)'

/**
 * A credential behind its label, for the providers that issue an unprefixed key.
 * The label and the separator stay, so the reader still learns which field the
 * provider rejected. A label can arrive quoted, because a framework that wraps a
 * failure often serializes the request to JSON first.
 */
const LABELED_CREDENTIAL = new RegExp(
    `((?:x-)?(?:${SECRET_WORD}|token)["']?\\s*[:=]\\s*)(?:"[^"\\n]*"|'[^'\\n]*'|[^\\s,;)}\\]]+)`,
    'gi'
)

const PRIVATE_KEY_BLOCK = /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g

/**
 * Names whose value is withheld whole. A structured error payload holds the
 * credential under a key rather than in a sentence, so no pattern in the text
 * matches it. `cookie` is here because a forwarded session cookie authenticates
 * the caller as much as a token does.
 */
const SENSITIVE_KEY_PATTERN = new RegExp(`${SECRET_WORD}|private[-_]?key|cookie|(^|[-_])(token|keys?)$`, 'i')

/**
 * Replace every credential-shaped substring of an error message with
 * `[redacted]`. The labeled form runs before the prefixed one, so a labeled key
 * is redacted once as a whole value rather than twice.
 */
export function redactCredentialsInText(text: string): string {
    return text
        .replace(PRIVATE_KEY_BLOCK, REDACTED)
        .replace(LABELED_CREDENTIAL, `$1${REDACTED}`)
        .replace(AUTH_SCHEME_CREDENTIAL, REDACTED)
        .replace(PREFIXED_CREDENTIAL, REDACTED)
}

/**
 * Redact an error value of any shape. A provider error arrives as a sentence, as
 * a parsed JSON body, or as the framework's own wrapper around either, so the
 * walk covers the nested strings as well as the top-level one.
 */
export function redactCredentials(value: unknown): unknown {
    if (typeof value === 'string') {
        return redactCredentialsInText(value)
    }
    if (Array.isArray(value)) {
        return value.map(redactCredentials)
    }
    if (isRecord(value)) {
        const out: Record<string, unknown> = {}
        for (const [key, nested] of Object.entries(value)) {
            assignKey(out, key, SENSITIVE_KEY_PATTERN.test(key) ? REDACTED : redactCredentials(nested))
        }
        return out
    }
    return value
}
