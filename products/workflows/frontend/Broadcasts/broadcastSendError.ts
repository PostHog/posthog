import type { BroadcastChannel } from './broadcastsLogic'

/** Picks the banner's action: fix the content, send again, or nothing. */
export type BroadcastSendErrorKind = 'content' | 'our_side' | 'unknown'

export interface BroadcastSendError {
    kind: BroadcastSendErrorKind
    /** Why the sends errored, in plain language and without a trailing period. */
    reason: string
    /** The merge tag or filter the sender has to find, written as it appears in the editor. */
    tag: string | null
    /** What the sender can do about it, as a full sentence. Null when it depends on how many people got the email. */
    nextStep: string | null
}

// The hog flow executor logs `[Action:<step id>] Errored: <String(err)>`, and String(err) adds the error class.
const LOG_PREFIX = /^(?:\[Action:[^\]]*\]\s*)?(?:Errored:\s*)?(?:[A-Za-z]*Error:\s*)*/
// LiquidJS adds the position in the rendered template, which the sender can't map back to the editor.
const TEMPLATE_POSITION = /,\s*line:\d+,\s*col:\d+\s*$/
// Template text inside a link's URL is URL-encoded, so a tag there reaches Liquid as `%20person.name%20`.
const URL_ENCODED = /%[0-9A-Fa-f]{2}/
const TRUNCATION_MARKER = '...'
const SENDER_NOT_SET_UP =
    /^Email integration not found|is not an email channel|email integration is not configured correctly/i
const PROVIDER_FAILED = /^Failed to send email via SES|^SES is not configured|^No messageId returned from SES/i
const ON_OUR_SIDE =
    /timed? ?out|ECONNRESET|ECONNREFUSED|ETIMEDOUT|socket hang up|rate limit|too many requests|\b5\d\d\b/i

const EXPRESSION_ERROR = /^(?:invalid value expression:|unexpected character) "(.*)"$/

function describeExpressionError(expression: string, noun: string, inLink: boolean): BroadcastSendError {
    const tag = expression.endsWith(TRUNCATION_MARKER) ? expression : `{{ ${expression} }}`
    if (inLink) {
        return {
            kind: 'content',
            reason: 'A merge tag in a link is broken',
            tag,
            nextStep: 'Edit the link and type the tag again.',
        }
    }
    return {
        kind: 'content',
        reason: "A merge tag can't be read",
        tag,
        nextStep: `Check the tag in the ${noun} for typos.`,
    }
}

function decodeUrlEncoding(text: string): string {
    try {
        return decodeURIComponent(text)
    } catch {
        // A lone `%` makes the whole string invalid, so decode each escape on its own instead.
        return text.replace(/%[0-9A-Fa-f]{2}/g, (escape) => {
            try {
                return decodeURIComponent(escape)
            } catch {
                return escape
            }
        })
    }
}

export function describeSendError(logMessage: string, channel: BroadcastChannel = 'email'): BroadcastSendError {
    const noun = channel === 'push' ? 'notification' : 'email'
    const firstLine = logMessage.trim().split('\n')[0]
    const rawMessage = firstLine.replace(LOG_PREFIX, '').replace(TEMPLATE_POSITION, '').trim()
    const message = decodeUrlEncoding(rawMessage).trim()

    const expression = EXPRESSION_ERROR.exec(message)?.[1].trim()
    if (expression) {
        return describeExpressionError(expression, noun, URL_ENCODED.test(rawMessage))
    }
    if (SENDER_NOT_SET_UP.test(message)) {
        return {
            kind: 'content',
            reason: `The sender for this ${noun} isn't set up`,
            tag: null,
            nextStep: `Pick a sender in the ${noun} step, then send it again.`,
        }
    }
    if (PROVIDER_FAILED.test(message) || ON_OUR_SIDE.test(message)) {
        return { kind: 'our_side', reason: 'A problem on our side stopped the send', tag: null, nextStep: null }
    }
    return {
        kind: 'unknown',
        reason: 'Sending hit an error',
        tag: null,
        nextStep: 'Show details has the error from the send.',
    }
}

function normalizeExpression(expression: string): string {
    return decodeUrlEncoding(expression).replace(/\s+/g, ' ').trim()
}

/** Liquid cuts long expressions in its error, so this finds the full tag in the content, or keeps the tag as is. */
export function findMergeTag(tag: string, content: string): string {
    if (!tag.endsWith(TRUNCATION_MARKER)) {
        return tag
    }
    const prefix = normalizeExpression(tag.slice(0, -TRUNCATION_MARKER.length))
    for (const [, inner] of decodeUrlEncoding(content).matchAll(/\{\{([\s\S]*?)\}\}/g)) {
        const expression = normalizeExpression(inner)
        if (prefix && expression.startsWith(prefix)) {
            return `{{ ${expression} }}`
        }
    }
    return tag
}
