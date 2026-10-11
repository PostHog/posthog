import type { WorkflowIdeaApi } from '../../generated/api.schemas'

// Lift assumed in the example, kept low so the card does not promise more than these emails tend to win back.
export const EXAMPLE_LIFT = 0.02

const WAIT_UNITS: Record<string, [string, string]> = {
    m: ['minute', 'minutes'],
    h: ['hour', 'hours'],
    d: ['day', 'days'],
    w: ['week', 'weeks'],
}

/** "1h" becomes "1 hour", "2d" becomes "2 days". */
export function waitLabel(wait: string): string {
    const match = /^(\d+)([mhdw])$/.exec(wait.trim())
    if (!match) {
        return wait
    }
    const count = Number(match[1])
    const [one, many] = WAIT_UNITS[match[2]]
    return `${count} ${count === 1 ? one : many}`
}

export interface IdeaEmailPreview {
    subject: string
    preheader: string
    html: string
    buttonLinks: string[]
}

export function ideaEmails(definition: WorkflowIdeaApi['definition']): IdeaEmailPreview[] {
    const actions = Array.isArray(definition.actions) ? (definition.actions as Record<string, any>[]) : []
    return actions
        .filter((action) => action.type === 'function_email')
        .map((action) => {
            const value = action.config?.inputs?.email?.value ?? {}
            const html: string = value.html ?? ''
            const buttonLinks = Array.from(html.matchAll(/href="(https?:[^"]+)"/g), (match) => match[1])
            return { subject: value.subject ?? '', preheader: value.preheader ?? '', html, buttonLinks }
        })
}

/** Extra goals a month if the example lift happened, or null when the idea has no audience size. */
export function exampleExtraPerMonth(evidence: WorkflowIdeaApi['evidence']): number | null {
    if (!evidence.reachable_people) {
        return null
    }
    return Math.round(evidence.reachable_people * EXAMPLE_LIFT)
}

export function siteHost(siteUrl: string | null | undefined): string | null {
    if (!siteUrl) {
        return null
    }
    try {
        return new URL(siteUrl).host
    } catch {
        return siteUrl
    }
}

// Matches SITE_PLACEHOLDER in the backend draft builder.
export const SITE_PLACEHOLDER = 'https://your-website.example'

/** "acme.com/" becomes "https://acme.com", or null when it isn't a website address. */
export function normalizeSite(input: string): string | null {
    const trimmed = input.trim()
    if (!trimmed) {
        return null
    }
    try {
        const url = new URL(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`)
        if (!url.hostname.includes('.')) {
            return null
        }
        return `${url.origin}${url.pathname}`.replace(/\/+$/, '')
    } catch {
        return null
    }
}

/** Points every button of an idea's emails at the person's website. */
export function withSite(definition: Record<string, unknown>, site: string): Record<string, unknown> {
    return JSON.parse(JSON.stringify(definition).split(SITE_PLACEHOLDER).join(site))
}

// Email list prices: the first 10,000 a month are free, then $3 per 1,000 up to 50,000, then $1.20 per 1,000.
const FREE_EMAILS = 10_000
const FIRST_TIER_END = 50_000

/** Rough monthly email cost of one workflow on its own, in dollars. */
export function estimatedMonthlyCost(emailsPerMonth: number): number {
    const firstTier = Math.max(0, Math.min(emailsPerMonth, FIRST_TIER_END) - FREE_EMAILS)
    const secondTier = Math.max(0, emailsPerMonth - FIRST_TIER_END)
    return Math.round((firstTier * 3 + secondTier * 1.2) / 1000)
}
