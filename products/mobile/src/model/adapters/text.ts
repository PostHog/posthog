import type { Headline } from '../types'

export function plainText(markdown: string): string {
    return markdown
        .replace(/\[([^\]]*)\]\(chart:[^)]*\)/g, '')
        .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
        .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/^#{1,6}\s+/gm, '')
        .replace(/^\s*[-*+]\s+/gm, '')
        .replace(/(\*\*|__)(.+?)\1/g, '$2')
        .replace(/(^|[^\w*])[*_]([^*_\n]+)[*_](?=[^\w*]|$)/g, '$1$2')
        .replace(/`([^`]*)`/g, '$1')
        .replace(/\s+/g, ' ')
        .trim()
}

// A sentence ends at `.`, `!` or `?` followed by a space and a capital letter or a digit, so "v1.2" does not split.
export function firstSentence(text: string): string {
    const match = /^(.+?[.!?])\s+(?=[A-Z0-9"“(])/.exec(text)
    return (match?.[1] ?? text).trim()
}

export function truncate(text: string, max: number): string {
    if (text.length <= max) {
        return text
    }
    const cut = text.slice(0, max - 1)
    const space = cut.lastIndexOf(' ')
    return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.]+$/, '')}…`
}

export function humanize(value: string): string {
    const words = value.replace(/[-_]+/g, ' ').trim().toLowerCase()
    return words.charAt(0).toUpperCase() + words.slice(1)
}

const AMOUNT = String.raw`[+\-−]?[$€£]?\d[\d,]*(?:\.\d+)?(?:[kKmMbB]|ms|s|%|x)?`

// The token must end at a space, so "5xx errors" and "v1.2" are not numbers.
const LEADING_NUMBER = new RegExp(String.raw`^(${AMOUNT}(?: of ${AMOUNT})?)\s+(\S.*)$`, 's')

export function splitLeadingNumber(text: string): Headline {
    const trimmed = text.trim()
    const match = LEADING_NUMBER.exec(trimmed)
    if (!match?.[1] || !match[2]) {
        return { rest: trimmed }
    }
    return { number: match[1], rest: match[2] }
}

const HEADLINE_MAX = 120

export function headlineFor(title: string, todayLead: string | undefined): Headline {
    const fromTitle = splitLeadingNumber(title)
    if (fromTitle.number) {
        return fromTitle
    }
    if (todayLead) {
        const sentence = firstSentence(plainText(todayLead)).replace(/\.$/, '')
        const fromLead = splitLeadingNumber(sentence)
        if (fromLead.number && sentence.length <= HEADLINE_MAX) {
            return fromLead
        }
    }
    return { rest: title.trim() }
}

// Written by hand instead of with Intl so the output is identical in Hermes, the web build and Jest.
export function groupThousands(value: number, decimals: number = 0): string {
    const fixed = Math.abs(value).toFixed(decimals)
    const [whole = '0', fraction] = fixed.split('.')
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    const trimmedFraction = fraction?.replace(/0+$/, '')
    return `${value < 0 ? '-' : ''}${grouped}${trimmedFraction ? `.${trimmedFraction}` : ''}`
}

export function plural(count: number, singular: string, pluralForm: string = `${singular}s`): string {
    return `${groupThousands(count)} ${count === 1 ? singular : pluralForm}`
}
