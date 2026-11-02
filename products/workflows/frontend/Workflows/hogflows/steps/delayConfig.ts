import type { HogFlowAction } from '../types'
import { isDuration, parseDuration, splitPartialDuration } from './durations'

const AUTO_DESCRIPTION_REGEX = /^Wait for \d*\.?\d+ (second|minute|hour|day)s?\.$/
const LEGACY_DEFAULT_DESCRIPTION = 'Wait for a specified duration.'
const UNCONFIGURED_UNTIL_DESCRIPTION = 'Wait until a date on the person or event.'

// A property key only reads back as `person.properties.foo` when it is a bare identifier. Anything
// else (spaces, a leading $, punctuation) has to go through brackets to survive the round trip.
const BARE_IDENTIFIER_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/
// An event's own properties are `properties.foo`, with no prefix: the expression runs against the same
// globals as a filter, where `event` is the event's name rather than an object. `event.properties.foo`
// reads a field off that string, resolves to nothing, and aborts every run of the step.
const DOTTED_EXPRESSION_REGEX = /^(?:(person)\.)?properties\.([A-Za-z_][A-Za-z0-9_]*)$/
const BRACKETED_EXPRESSION_REGEX = /^(?:(person)\.)?properties\['((?:[^'\\]|\\.)*)'\]$/

const UNIT_LABELS: Record<string, string> = {
    s: 'second',
    m: 'minute',
    h: 'hour',
    d: 'day',
}

export type DelayActionConfig = Extract<HogFlowAction, { type: 'delay' }>['config']

export type DelayMode = 'duration' | 'until'
/** 'on' means no offset at all: wait for the date itself. */
export type DelayOffsetDirection = 'on' | 'before' | 'after'
export type DelayPropertySource = 'person' | 'event'

export interface DelayProperty {
    source: DelayPropertySource
    key: string
}

export interface DelayOffset {
    /** An unsigned duration string, the same shape HogFlowDuration edits. */
    duration: string
    direction: DelayOffsetDirection
}

/** Only the fields the timezone controls change, merged onto whatever else delay_until holds. */
export interface DelayTimezone {
    timezone?: string | null
    use_person_timezone?: boolean
    fallback_timezone?: string | null
}

/** Matches the executor's default when no zone is configured. */
export const DEFAULT_DELAY_TIMEZONE = 'UTC'

export const DEFAULT_DELAY_DURATION = '10m'
// Mirrors the executor's cap in nodejs/src/cdp/services/hogflows/actions/delay.ts.
export const DEFAULT_MAX_DELAY_DURATION = '30d'

export function getDelayMode(config: DelayActionConfig): DelayMode {
    return config.delay_until ? 'until' : 'duration'
}

export function buildDelayExpression({ source, key }: DelayProperty): string {
    const prefix = source === 'person' ? 'person.properties' : 'properties'
    if (BARE_IDENTIFIER_REGEX.test(key)) {
        return `${prefix}.${key}`
    }
    return `${prefix}['${key.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}']`
}

/** Null for an expression the builder did not compose, e.g. hand-written SQL saved through the API. */
export function parseDelayExpression(expression: string): DelayProperty | null {
    const dotted = expression.match(DOTTED_EXPRESSION_REGEX)
    if (dotted) {
        return { source: dotted[1] === 'person' ? 'person' : 'event', key: dotted[2] }
    }
    const bracketed = expression.match(BRACKETED_EXPRESSION_REGEX)
    if (bracketed) {
        return { source: bracketed[1] === 'person' ? 'person' : 'event', key: bracketed[2].replace(/\\(.)/g, '$1') }
    }
    return null
}

/** Undefined for direction 'on', so "wait for the date itself" saves no offset at all. */
export function buildDelayOffset({ duration, direction }: DelayOffset): string | undefined {
    if (direction === 'on' || !isDuration(duration)) {
        return undefined
    }
    return `${direction === 'before' ? '-' : ''}${duration}`
}

export function parseDelayOffset(offset: string | undefined): DelayOffset {
    const parsed = offset ? parseDuration(offset) : null
    if (!parsed) {
        // A day is the offset almost every reminder uses, so it is the amount to start from once
        // someone switches off 'on'.
        return { duration: '1d', direction: 'on' }
    }
    return { duration: `${parsed.amountText}${parsed.unit}`, direction: parsed.negative ? 'before' : 'after' }
}

/** "2 days" for '2d'. Null when there is no number to read, e.g. a cleared duration input. */
export function getDurationText(duration: string): string | null {
    const { amountText, unit } = splitPartialDuration(duration)
    const number = parseFloat(amountText)
    if (!Number.isFinite(number)) {
        return null
    }
    const unitLabel = UNIT_LABELS[unit] ?? 'minute'
    return `${number} ${unitLabel}${number !== 1 ? 's' : ''}`
}

export function getDelayDescription(config: DelayActionConfig): string {
    if (config.delay_until) {
        const expression = config.delay_until.expression
        if (!expression.trim()) {
            return UNCONFIGURED_UNTIL_DESCRIPTION
        }
        // The property name alone reads better than the expression it was composed from, but an
        // expression the builder cannot read back has nothing shorter to show.
        const dateText = parseDelayExpression(expression)?.key ?? expression
        const offsetText = getDurationText(config.delay_until.offset?.replace('-', '') ?? '')
        if (!offsetText || !config.delay_until.offset) {
            return `Wait until ${dateText}.`
        }
        const direction = config.delay_until.offset.startsWith('-') ? 'before' : 'after'
        return `Wait until ${offsetText} ${direction} ${dateText}.`
    }

    // No valid number yet (e.g. the input was cleared) - keep a neutral description
    const durationText = getDurationText(config.delay_duration ?? '')
    return durationText ? `Wait for ${durationText}.` : LEGACY_DEFAULT_DESCRIPTION
}

export function shouldAutoUpdateDescription(description: string | undefined, config?: DelayActionConfig): boolean {
    return (
        // Agent-created actions can arrive with no description at all, so treat an absent one like an empty one.
        !description ||
        description.trim() === '' ||
        AUTO_DESCRIPTION_REGEX.test(description) ||
        description === LEGACY_DEFAULT_DESCRIPTION ||
        description === UNCONFIGURED_UNTIL_DESCRIPTION ||
        // An until-mode description ends in a property name, which no regex can tell apart from a
        // description someone typed. Comparing against what the step's current config generates
        // identifies the auto-written one exactly.
        (config !== undefined && description === getDelayDescription(config))
    )
}
