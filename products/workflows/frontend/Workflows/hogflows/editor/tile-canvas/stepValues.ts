import { isFunctionAction } from '../../steps/types'
import type { HogFlowAction } from '../../types'

export type ActionOf<T extends HogFlowAction['type']> = Extract<HogFlowAction, { type: T }>

const DURATION_UNITS: Record<string, [string, string]> = {
    s: ['second', 'seconds'],
    m: ['minute', 'minutes'],
    h: ['hour', 'hours'],
    d: ['day', 'days'],
    w: ['week', 'weeks'],
}

export function humanDuration(raw: string | undefined | null): string {
    const parts = /^(\d+(?:\.\d+)?)\s*([smhdw])$/.exec(raw ?? '')
    if (!parts) {
        return raw ?? ''
    }
    const count = Number(parts[1])
    const [one, many] = DURATION_UNITS[parts[2]]
    return `${count} ${count === 1 ? one : many}`
}

export const asText = (value: unknown): string | undefined =>
    typeof value === 'string' && value.trim() ? value : typeof value === 'number' ? String(value) : undefined

export const asTextList = (value: unknown): string[] =>
    Array.isArray(value) ? value.flatMap((item) => asText(item) ?? []) : []

export const asRecord = (value: unknown): Record<string, unknown> =>
    value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

/** A person or event property value as someone would type it: true, 42, or the text itself. */
export function propertyValueText(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'boolean' || typeof value === 'number') {
        return String(value)
    }
    return value === null || value === undefined ? '' : JSON.stringify(value)
}

export function inputValue(action: HogFlowAction, key: string): unknown {
    return isFunctionAction(action) ? action.config.inputs?.[key]?.value : undefined
}

export function templateIdOf(action: HogFlowAction): string | undefined {
    return isFunctionAction(action) ? action.config.template_id : undefined
}

export function plainVariables(text: string): string {
    return text.replace(/\{\{?\s*(?:[a-z_]+\.)*([a-z_]+)\s*\}?\}/gi, (_, key: string) => key.replace(/_/g, ' '))
}

export const firstLine = (text: string): string => text.split('\n')[0]
export const firstSentence = (text: string): string => text.split(/(?<=[.!?])\s/)[0]
export const humanKey = (key: string): string => key.replace(/^\$/, '').replace(/_/g, ' ')
export const joinList = (items: string[]): string => items.map(humanKey).join(', ')

function propertyFilterText(filter: unknown): string {
    const { key, value, operator } = asRecord(filter)
    const values = Array.isArray(value)
        ? value.map(propertyValueText).filter(Boolean).join(' or ')
        : propertyValueText(value)
    const verb = typeof operator === 'string' && operator !== 'exact' ? operator.replace(/_/g, ' ') : 'is'
    return `${humanKey(asText(key) ?? 'property')} ${verb} ${values}`.trim()
}

export function eventNames(events: unknown): string[] {
    return (Array.isArray(events) ? events : []).flatMap((event) => {
        const { name, id } = asRecord(event)
        return asText(name) ?? asText(id) ?? []
    })
}

export function conditionText(filters: unknown): string {
    const { events, properties } = asRecord(filters)
    const parts = [
        ...eventNames(events).map((name) => `did ${name}`),
        ...(Array.isArray(properties) ? properties : []).map(propertyFilterText),
    ]
    return parts.length ? parts.join(' and ') : 'everyone'
}

export function outputKeys(action: HogFlowAction): string[] {
    const output = action.output_variable
    const list = Array.isArray(output) ? output : output ? [output] : []
    return list.map((variable) => variable.key)
}

export interface EmailContent {
    subject: string
    preheader?: string
    to: string
    html?: string
    text?: string
}

export function emailContent(action: HogFlowAction): EmailContent | undefined {
    if (templateIdOf(action) !== 'template-email') {
        return undefined
    }
    const email = asRecord(inputValue(action, 'email'))
    const toEmail = asText(asRecord(email.to).email) ?? ''
    return {
        subject: asText(email.subject) ?? 'No subject yet',
        preheader: asText(email.preheader),
        to: /person\.properties\.email/.test(toEmail) ? 'Their email address' : toEmail || 'Not set',
        html: asText(email.html),
        text: asText(email.text),
    }
}
