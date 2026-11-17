// PROTOTYPE (ticket #385), throwaway. Invented emails for the transactional list, each with its own impact numbers.
import type { JourneyCase } from './useEmailJourneyPrototype'

export interface ListEmail {
    id: string
    name: string
    source: 'code' | 'template'
    description: string
    tags: string[]
    /** Sends per day over the last 30 days. */
    daily: number[]
    sent: number
    delivered: number
    /** Null when opens and clicks aren't tracked, as for a sensitive email. */
    opened: number | null
    clicked: number | null
    landed: number | null
    goal: string | null
    converted: number | null
    scanner: { question: string; problems: number; topProblem: string | null } | null
    /** The email's impact page in the prototype; only one email has one. */
    hasImpactPage: boolean
}

function daily(base: number, trend: number, seed: number): number[] {
    return Array.from({ length: 30 }, (_, day) =>
        Math.max(0, Math.round(base * (1 + trend * (day / 30)) * (0.75 + ((day * seed) % 7) / 14)))
    )
}

const EMAILS: ListEmail[] = [
    {
        id: 'trial-ending',
        name: 'trial-ending',
        source: 'code',
        description: 'Your Hedgebox trial ends in 3 days',
        tags: ['lifecycle'],
        daily: daily(400, 0.3, 3),
        sent: 12480,
        delivered: 12301,
        opened: 7020,
        clicked: 1912,
        landed: 1604,
        goal: 'plan upgraded',
        converted: 412,
        scanner: {
            question: 'Do people finish what this email asked them to do?',
            problems: 3,
            topProblem: 'Card declined on the payment form, then left',
        },
        hasImpactPage: true,
    },
    {
        id: 'password-reset',
        name: 'password-reset',
        source: 'code',
        description: 'Reset your Hedgebox password',
        tags: ['auth'],
        daily: daily(1600, 0, 5),
        sent: 48210,
        delivered: 48022,
        opened: 39100,
        clicked: 30950,
        landed: 29870,
        goal: 'password changed',
        converted: 27420,
        scanner: null,
        hasImpactPage: false,
    },
    {
        id: 'welcome',
        name: 'Welcome to Hedgebox',
        source: 'template',
        description: 'Sent once a person signs up',
        tags: ['onboarding'],
        daily: daily(310, 0.15, 2),
        sent: 9302,
        delivered: 9250,
        opened: 5640,
        clicked: 2130,
        landed: 1980,
        goal: 'file uploaded',
        converted: 870,
        scanner: {
            question: 'Where do people get stuck after clicking?',
            problems: 1,
            topProblem: 'Upload dialog closed before the file finished',
        },
        hasImpactPage: false,
    },
    {
        id: 'invoice-receipt',
        name: 'invoice-receipt',
        source: 'code',
        description: 'Your Hedgebox invoice',
        tags: ['billing'],
        daily: daily(90, 0, 4),
        sent: 2710,
        delivered: 2704,
        opened: null,
        clicked: null,
        landed: null,
        goal: null,
        converted: null,
        scanner: null,
        hasImpactPage: false,
    },
    {
        id: 'invite',
        name: "You're invited to a shared folder",
        source: 'template',
        description: 'Sent when someone shares a folder',
        tags: ['growth'],
        daily: daily(105, -0.2, 6),
        sent: 3140,
        delivered: 3101,
        opened: 2010,
        clicked: 1190,
        landed: 1102,
        goal: null,
        converted: null,
        scanner: null,
        hasImpactPage: false,
    },
    {
        id: 'usage-limit',
        name: 'usage-limit-warning',
        source: 'code',
        description: "You've used 90% of your storage",
        tags: ['lifecycle', 'billing'],
        daily: daily(34, 0.6, 1),
        sent: 1020,
        delivered: 1012,
        opened: 690,
        clicked: 92,
        landed: 80,
        goal: 'plan upgraded',
        converted: 6,
        scanner: null,
        hasImpactPage: false,
    },
]

export function listData(journeyCase: JourneyCase): ListEmail[] {
    return EMAILS.map((email) => {
        if (journeyCase === 'no-landing') {
            return { ...email, landed: null, scanner: null }
        }
        if (journeyCase === 'no-recording') {
            return { ...email, scanner: null }
        }
        return email
    })
}

/** Conversion as a share of the people who clicked, or of recipients when clicks aren't tracked. */
export function conversionRate(email: ListEmail): number | null {
    if (email.converted === null) {
        return null
    }
    return email.converted / (email.clicked ?? email.delivered)
}
