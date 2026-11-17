// PROTOTYPE (ticket #385), throwaway. Invented numbers for one transactional email across all its sends, reshaped per
// simulated case. Nothing here comes from a real project.
import type { JourneySession } from './journeyFixtures'
import type { JourneyCase } from './useEmailJourneyPrototype'

export interface ImpactLink {
    key: string
    label: string
    url: string
    /** Only links on the sending domain carry the run tag, so only they can be followed to a session. */
    tagged: boolean
    clickedPeople: number
    sessions: number | null
    converted: number | null
}

export interface ImpactExcerpt {
    person: string
    text: string
    /** Where in the recording the excerpt happens, as seconds from the landing. */
    atSeconds: number
    session: JourneySession
}

export interface ImpactFinding {
    id: string
    title: string
    tone: 'problem' | 'success' | 'neutral'
    sessions: number
    linkKey: string
    excerpts: ImpactExcerpt[]
}

export interface ImpactScanner {
    name: string
    type: 'Categorize'
    prompt: string
    scanned: number
    /** One sentence the scanner writes across its findings. */
    summary: string | null
    findings: ImpactFinding[]
}

export interface ImpactGoal {
    event: string
    windowDays: number
}

export interface ImpactData {
    key: string
    subject: string
    sendingDomain: string
    period: string
    sent: number
    delivered: number
    /** Null when opens and clicks aren't tracked. */
    opened: number | null
    clicked: number | null
    /** People whose click started a session. Null when the link tag can't be followed. */
    landed: number | null
    goal: ImpactGoal | null
    /** Recipients who did the goal event within the window after their click. */
    converted: number | null
    /** Conversion among recipients who didn't click, within the window after the send. */
    convertedWithoutClick: { people: number; of: number } | null
    links: ImpactLink[]
    scanner: ImpactScanner | null
    recordingsOn: boolean
    runTagOn: boolean
}

export const GOAL_OPTIONS = ['plan upgraded', 'file shared', 'invite sent']

function session(
    id: string,
    landing: string,
    device: string,
    durationSeconds: number,
    events: [string, string, boolean?][]
): JourneySession {
    return {
        id,
        startedAt: events[0][0],
        durationSeconds,
        device,
        landing,
        pages: events.length + 1,
        events: events.map(([at, label, outcome]) => ({ at, label, outcome })),
        who: 'recipient',
        recording: true,
    }
}

const FINDINGS: ImpactFinding[] = [
    {
        id: 'declined',
        title: 'Card declined on the payment form, then left',
        tone: 'problem',
        sessions: 214,
        linkKey: 'upgrade',
        excerpts: [
            {
                person: 'jonas.weber@example.com',
                text: 'Picked Annual, entered a card, saw "Card declined" twice, then closed the tab.',
                atSeconds: 252,
                session: session('019a8d10-0001-7000-8000-000000000001', '/billing', 'Desktop · Chrome', 281, [
                    ['2026-11-12T09:02:10Z', 'Viewed /billing'],
                    ['2026-11-12T09:03:01Z', 'Clicked "Annual"'],
                    ['2026-11-12T09:06:22Z', 'Saw "Card declined"'],
                    ['2026-11-12T09:06:58Z', 'Saw "Card declined"'],
                ]),
            },
            {
                person: 'amara.okafor@example.com',
                text: 'Tried two cards. The second failed with the same message, and she gave up at the address step.',
                atSeconds: 198,
                session: session('019a8d10-0002-7000-8000-000000000002', '/billing', 'Desktop · Safari', 240, [
                    ['2026-11-13T14:20:00Z', 'Viewed /billing'],
                    ['2026-11-13T14:23:18Z', 'Saw "Card declined"'],
                ]),
            },
        ],
    },
    {
        id: 'upgraded',
        title: 'Upgraded without trouble',
        tone: 'success',
        sessions: 398,
        linkKey: 'upgrade',
        excerpts: [
            {
                person: 'mia.jensen@example.com',
                text: 'Compared plans on /pricing, picked Annual and finished checkout in under four minutes.',
                atSeconds: 248,
                session: session('019a8c31-02aa-7d10-b3c4-1f2e3d4c5b6a', '/billing', 'Desktop · Chrome', 402, [
                    ['2026-11-16T08:12:43Z', 'Viewed /billing'],
                    ['2026-11-16T08:13:20Z', 'Viewed /pricing'],
                    ['2026-11-16T08:16:51Z', 'plan upgraded', true],
                ]),
            },
        ],
    },
    {
        id: 'monthly',
        title: 'Looked for a monthly plan and didn’t find one',
        tone: 'problem',
        sessions: 167,
        linkKey: 'upgrade',
        excerpts: [
            {
                person: 'lea.brandt@example.com',
                text: 'Toggled between plans on /pricing three times, searched the FAQ for "monthly", then left.',
                atSeconds: 95,
                session: session('019a8d10-0003-7000-8000-000000000003', '/billing', 'Desktop · Firefox', 190, [
                    ['2026-11-14T17:40:00Z', 'Viewed /billing'],
                    ['2026-11-14T17:41:10Z', 'Viewed /pricing'],
                ]),
            },
        ],
    },
    {
        id: 'files',
        title: 'Browsed files and never opened billing',
        tone: 'neutral',
        sessions: 289,
        linkKey: 'files',
        excerpts: [
            {
                person: 'tom.fischer@example.com',
                text: 'Opened two shared folders, downloaded a PDF, and left without visiting billing.',
                atSeconds: 60,
                session: session('019a8d10-0004-7000-8000-000000000004', '/files', 'Mobile · Safari', 140, [
                    ['2026-11-15T07:10:00Z', 'Viewed /files'],
                    ['2026-11-15T07:11:00Z', 'Downloaded q3-report.pdf'],
                ]),
            },
        ],
    },
    {
        id: 'notfound',
        title: 'Landed on a "Page not found" on mobile',
        tone: 'problem',
        sessions: 38,
        linkKey: 'upgrade',
        excerpts: [
            {
                person: 'sara.lindqvist@example.com',
                text: 'The billing link opened a 404 in the mobile app’s browser. She tapped back and didn’t return.',
                atSeconds: 4,
                session: session('019a8d10-0005-7000-8000-000000000005', '/billing', 'Mobile · Safari', 12, [
                    ['2026-11-15T21:00:00Z', 'Viewed /billing (404)'],
                ]),
            },
        ],
    },
]

function base(): ImpactData {
    return {
        key: 'trial-ending',
        subject: 'Your Hedgebox trial ends in 3 days',
        sendingDomain: 'mail.hedgebox.net',
        period: 'Last 30 days',
        sent: 12480,
        delivered: 12301,
        opened: 7020,
        clicked: 1912,
        landed: 1604,
        goal: { event: 'plan upgraded', windowDays: 7 },
        converted: 412,
        convertedWithoutClick: { people: 218, of: 10389 },
        links: [
            {
                key: 'upgrade',
                label: 'Upgrade now',
                url: 'https://hedgebox.net/billing',
                tagged: true,
                clickedPeople: 1488,
                sessions: 1301,
                converted: 398,
            },
            {
                key: 'files',
                label: 'See your files',
                url: 'https://hedgebox.net/files',
                tagged: true,
                clickedPeople: 512,
                sessions: 303,
                converted: 14,
            },
            {
                key: 'faq',
                label: 'Pricing FAQ',
                url: 'https://help.hedgebox-docs.com/pricing',
                tagged: false,
                clickedPeople: 241,
                sessions: null,
                converted: null,
            },
        ],
        scanner: {
            name: 'What happened after "Trial ending"',
            type: 'Categorize',
            prompt: 'What did the person do after landing from this email, and what stopped them from upgrading?',
            scanned: 1240,
            summary:
                'Most people who clicked "Upgrade now" and didn’t upgrade left at the payment form after a declined card. A smaller group looked for a monthly plan, and 38 mobile visitors hit a "Page not found" on /billing.',
            findings: FINDINGS,
        },
        recordingsOn: true,
        runTagOn: true,
    }
}

export function impactData(journeyCase: JourneyCase): ImpactData {
    const data = base()
    switch (journeyCase) {
        case 'no-scanner':
            data.scanner = null
            return data
        case 'scanning':
            data.scanner = {
                ...data.scanner!,
                scanned: 37,
                summary: null,
                findings: FINDINGS.slice(0, 2).map((finding) => ({
                    ...finding,
                    sessions: finding.id === 'declined' ? 9 : 14,
                })),
            }
            return data
        case 'no-goal':
            data.goal = null
            data.converted = null
            data.convertedWithoutClick = null
            data.links = data.links.map((link) => ({ ...link, converted: null }))
            return data
        case 'no-landing':
            // Conversion still works through the person on the send; sessions need the link tag.
            data.runTagOn = false
            data.landed = null
            data.scanner = null
            data.links = data.links.map((link) => ({ ...link, sessions: null }))
            return data
        case 'no-recording':
            data.recordingsOn = false
            data.scanner = null
            return data
        case 'not-tracked':
            data.opened = null
            data.clicked = null
            data.landed = null
            data.scanner = null
            data.converted = 630
            data.convertedWithoutClick = null
            data.links = []
            return data
        default:
            return data
    }
}

export function percent(part: number, whole: number): string {
    if (!whole) {
        return '0%'
    }
    const value = (part / whole) * 100
    return `${value >= 10 ? Math.round(value) : value.toFixed(1)}%`
}
