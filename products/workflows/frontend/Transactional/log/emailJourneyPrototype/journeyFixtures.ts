// PROTOTYPE (ticket #385), throwaway. Invented data for one send, reshaped per simulated case.
import type { JourneyCase } from './useEmailJourneyPrototype'

export interface JourneyLink {
    key: string
    label: string
    url: string
    /** Only links on the sending domain carry the run tag, so only they can be joined to a session. */
    tagged: boolean
}

export interface JourneySessionEvent {
    at: string
    label: string
    /** A custom event the product tracks, which reads as an outcome. */
    outcome?: boolean
}

export interface JourneySession {
    id: string
    startedAt: string
    durationSeconds: number
    device: string
    landing: string
    pages: number
    events: JourneySessionEvent[]
    /** Who the session belongs to: the recipient, a browser that isn't identified as them, or unknown (no person on the send). */
    who: 'recipient' | 'someone-else' | 'unlinked'
    recording: boolean
}

export interface JourneyClick {
    id: string
    at: string
    linkKey: string
    session: JourneySession | null
    /** Why no session joined this click. */
    noSession?: 'off-domain' | 'no-visit'
}

export interface JourneyPerson {
    name: string
    email: string
    distinctId: string
}

export interface JourneyData {
    messageId: string
    recipient: string
    subject: string
    emailName: string
    sendingDomain: string
    queuedAt: string
    sentAt: string
    deliveredAt: string
    openedAt: string | null
    person: JourneyPerson | null
    links: JourneyLink[]
    /** Null when clicks aren't tracked for this send. */
    clicks: JourneyClick[] | null
    /** The same person's sessions in the week after the send that no click started. */
    otherSessions: JourneySession[]
    engagementEventsOn: boolean
}

const RUN_ID = '019a8c2e-5f1b-7c3d-9e4a-6b2f8d1c0a57'

const LINKS: JourneyLink[] = [
    { key: 'upgrade', label: 'Upgrade now', url: 'https://hedgebox.net/billing', tagged: true },
    { key: 'files', label: 'See your files', url: 'https://hedgebox.net/files', tagged: true },
    { key: 'faq', label: 'Pricing FAQ', url: 'https://help.hedgebox-docs.com/pricing', tagged: false },
]

const UPGRADE_SESSION: JourneySession = {
    id: '019a8c31-02aa-7d10-b3c4-1f2e3d4c5b6a',
    startedAt: '2026-11-16T08:12:43Z',
    durationSeconds: 402,
    device: 'Desktop · Chrome · Berlin',
    landing: `/billing?ph_workflow_run=${RUN_ID}`,
    pages: 7,
    events: [
        { at: '2026-11-16T08:12:43Z', label: 'Viewed /billing' },
        { at: '2026-11-16T08:13:20Z', label: 'Viewed /pricing' },
        { at: '2026-11-16T08:14:02Z', label: 'Clicked "Annual"' },
        { at: '2026-11-16T08:16:51Z', label: 'plan upgraded', outcome: true },
        { at: '2026-11-16T08:17:30Z', label: 'Viewed /files' },
    ],
    who: 'recipient',
    recording: true,
}

const FILES_SESSION: JourneySession = {
    id: '019a8f02-77c1-7a9e-8d2b-4c5d6e7f8091',
    startedAt: '2026-11-16T19:05:14Z',
    durationSeconds: 125,
    device: 'Mobile · Safari · Berlin',
    landing: `/files?ph_workflow_run=${RUN_ID}`,
    pages: 3,
    events: [
        { at: '2026-11-16T19:05:14Z', label: 'Viewed /files' },
        { at: '2026-11-16T19:06:02Z', label: 'Viewed /files/q3-report.pdf' },
        { at: '2026-11-16T19:06:40Z', label: 'file shared', outcome: true },
    ],
    who: 'recipient',
    recording: true,
}

const LATER_SESSION: JourneySession = {
    id: '019a9301-1b2c-7d3e-8f40-516273849506',
    startedAt: '2026-11-17T07:58:10Z',
    durationSeconds: 731,
    device: 'Desktop · Chrome · Berlin',
    landing: '/home',
    pages: 11,
    events: [
        { at: '2026-11-17T07:58:10Z', label: 'Viewed /home' },
        { at: '2026-11-17T08:02:44Z', label: 'file uploaded', outcome: true },
    ],
    who: 'recipient',
    recording: true,
}

function base(): JourneyData {
    return {
        messageId: RUN_ID,
        recipient: 'mia.jensen@example.com',
        subject: 'Your Hedgebox trial ends in 3 days',
        emailName: 'Trial ending',
        sendingDomain: 'mail.hedgebox.net',
        queuedAt: '2026-11-16T08:00:01Z',
        sentAt: '2026-11-16T08:00:02Z',
        deliveredAt: '2026-11-16T08:00:04Z',
        openedAt: '2026-11-16T08:11:58Z',
        person: { name: 'Mia Jensen', email: 'mia.jensen@example.com', distinctId: 'user_8f3a21' },
        links: LINKS,
        clicks: [
            { id: 'c1', at: '2026-11-16T08:12:40Z', linkKey: 'upgrade', session: UPGRADE_SESSION },
            { id: 'c2', at: '2026-11-16T19:05:11Z', linkKey: 'files', session: FILES_SESSION },
            { id: 'c3', at: '2026-11-17T07:40:03Z', linkKey: 'faq', session: null, noSession: 'off-domain' },
        ],
        otherSessions: [LATER_SESSION],
        engagementEventsOn: true,
    }
}

export function journeyData(journeyCase: JourneyCase): JourneyData {
    const data = base()
    switch (journeyCase) {
        case 'other-person':
            data.clicks = data.clicks!.map((click) =>
                click.id === 'c2' && click.session
                    ? {
                          ...click,
                          session: { ...click.session, who: 'someone-else', device: 'Desktop · Firefox · Lisbon' },
                      }
                    : click
            )
            return data
        case 'no-person':
            data.person = null
            data.otherSessions = []
            data.clicks = data.clicks!.map((click) =>
                click.session ? { ...click, session: { ...click.session, who: 'unlinked' } } : click
            )
            return data
        case 'no-recording':
            data.clicks = data.clicks!.map((click) =>
                click.session ? { ...click, session: { ...click.session, recording: false } } : click
            )
            data.otherSessions = data.otherSessions.map((session) => ({ ...session, recording: false }))
            return data
        case 'no-landing':
            data.clicks = data.clicks!.map((click) => ({
                ...click,
                session: null,
                noSession: click.linkKey === 'faq' ? 'off-domain' : 'no-visit',
            }))
            return data
        case 'no-clicks':
            data.clicks = []
            return data
        case 'not-tracked':
            data.clicks = null
            data.openedAt = null
            return data
        case 'events-off':
            data.engagementEventsOn = false
            return data
        default:
            return data
    }
}

export function linkFor(data: JourneyData, key: string): JourneyLink {
    return data.links.find((link) => link.key === key) ?? data.links[0]
}

export function sessionsFromClicks(data: JourneyData): number {
    return (data.clicks ?? []).filter((click) => click.session).length
}
