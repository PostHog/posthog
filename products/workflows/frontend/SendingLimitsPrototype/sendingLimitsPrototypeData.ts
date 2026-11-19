// PROTOTYPE (branch prototype/sending-limits-ux): throwaway, never merge.
// Every number and name below is invented for the prototype. The ramp follows the plan's rule:
// today's allowance is the larger of a floor and 2x the peak clean day of the last 7 days, and a
// dirty 7-day window halves it.

export type VariantKey = 'A' | 'B' | 'C' | 'D'
export type StateKey = 'new' | 'warming' | 'capped' | 'moved-down' | 'blocked'
export type SurfaceKey = 'setup' | 'reputation' | 'broadcast'
export type DomainProfileKey = 'established' | 'starter' | 'lookup-failed' | 'brand-new' | 'listed'
export type DomainBand = 'Hold' | 'Starter' | 'Established'

export interface AllowanceMove {
    date: string
    from: number
    to: number
    reason: string
    direction: 'up' | 'down' | 'start'
}

export interface HeldBroadcast {
    name: string
    audience: number
    sentSoFar: number
    // Planned emails per day, starting today. The ramp grows the later days.
    plan: { date: string; emails: number }[]
    sample?: { size: number; heldUntil: string; bounceRate: number | null; verdict: 'checking' | 'passed' | 'stopped' }
}

export interface SendingState {
    key: StateKey
    label: string
    domain: string
    allowancePerDay: number
    ceilingPerDay: number
    tomorrowIfClean: number
    sentToday: number
    queued: number
    rates7d: { bounce: number; complaint: number; sent: number }
    rates30d: { bounce: number; complaint: number; sent: number }
    moves: AllowanceMove[]
    broadcast: HeldBroadcast
    blockedReason?: string
}

export const VARIANTS: { key: VariantKey; name: string; primarySurface: SurfaceKey }[] = [
    { key: 'A', name: 'Hide it', primarySurface: 'broadcast' },
    { key: 'B', name: 'Explain it', primarySurface: 'reputation' },
    { key: 'C', name: 'At broadcast time', primarySurface: 'broadcast' },
    { key: 'D', name: 'Check at sender setup', primarySurface: 'setup' },
]

// Filled from the usage brief: flag names and the controls they trip, never numbers.
export const VARIANT_USAGE_FLAGS: Record<VariantKey, string> = {
    A: 'muscle memory, known pain: workflows-request-sending-tier-increase moves to setup and the recipients step',
    B: 'muscle memory, known pain: workflows-sending-allowance · low use: the Reputation tab',
    C: 'muscle memory, known pain: broadcast-audience-over-limit · low use: broadcast-rate-limit-suggestion · channel shift: broadcasts-create MCP tool',
    D: 'low use: email-domain-ready-reputation · known pain: email-domain-check-again',
}

export const SURFACES: { key: SurfaceKey; label: string }[] = [
    { key: 'setup', label: 'Sender setup' },
    { key: 'reputation', label: 'Reputation page' },
    { key: 'broadcast', label: 'Broadcast' },
]

export const BOUNCE_LIMIT = 0.02
export const COMPLAINT_LIMIT = 0.001
export const CEILING = 100000

const DOMAIN = 'mail.example.com'
const BROADCAST_NAME = 'December product update'

export const STATES: Record<StateKey, SendingState> = {
    new: {
        key: 'new',
        label: 'New sender',
        domain: DOMAIN,
        allowancePerDay: 1000,
        ceilingPerDay: CEILING,
        tomorrowIfClean: 1000,
        sentToday: 0,
        queued: 0,
        rates7d: { bounce: 0, complaint: 0, sent: 0 },
        rates30d: { bounce: 0, complaint: 0, sent: 0 },
        moves: [
            {
                date: 'Dec 10',
                from: 0,
                to: 1000,
                reason: 'Sender verified. Every new sender starts here.',
                direction: 'start',
            },
        ],
        broadcast: {
            name: BROADCAST_NAME,
            audience: 6000,
            sentSoFar: 0,
            plan: [
                { date: 'Today', emails: 1000 },
                { date: 'Dec 11', emails: 2000 },
                { date: 'Dec 12', emails: 3000 },
            ],
            sample: { size: 300, heldUntil: '15:40', bounceRate: null, verdict: 'checking' },
        },
    },
    warming: {
        key: 'warming',
        label: 'Warming up',
        domain: DOMAIN,
        allowancePerDay: 4000,
        ceilingPerDay: CEILING,
        tomorrowIfClean: 8000,
        sentToday: 2600,
        queued: 0,
        rates7d: { bounce: 0.004, complaint: 0.0002, sent: 9800 },
        rates30d: { bounce: 0.005, complaint: 0.0002, sent: 11200 },
        moves: [
            {
                date: 'Dec 3',
                from: 0,
                to: 1000,
                reason: 'Sender verified. Every new sender starts here.',
                direction: 'start',
            },
            {
                date: 'Dec 5',
                from: 1000,
                to: 2000,
                reason: 'You sent 1,000 emails on Dec 4 with 0.3% bounces and no spam complaints.',
                direction: 'up',
            },
            {
                date: 'Dec 8',
                from: 2000,
                to: 4000,
                reason: 'You sent 2,000 emails on Dec 7 with 0.5% bounces and 0.02% spam complaints.',
                direction: 'up',
            },
        ],
        broadcast: {
            name: BROADCAST_NAME,
            audience: 3500,
            sentSoFar: 3500,
            plan: [{ date: 'Today', emails: 3500 }],
            sample: { size: 200, heldUntil: '09:40', bounceRate: 0.003, verdict: 'passed' },
        },
    },
    capped: {
        key: 'capped',
        label: 'Capped, send held',
        domain: DOMAIN,
        allowancePerDay: 4000,
        ceilingPerDay: CEILING,
        tomorrowIfClean: 8000,
        sentToday: 4000,
        queued: 21000,
        rates7d: { bounce: 0.004, complaint: 0.0002, sent: 9800 },
        rates30d: { bounce: 0.005, complaint: 0.0002, sent: 11200 },
        moves: [
            {
                date: 'Dec 3',
                from: 0,
                to: 1000,
                reason: 'Sender verified. Every new sender starts here.',
                direction: 'start',
            },
            {
                date: 'Dec 5',
                from: 1000,
                to: 2000,
                reason: 'You sent 1,000 emails on Dec 4 with 0.3% bounces and no spam complaints.',
                direction: 'up',
            },
            {
                date: 'Dec 8',
                from: 2000,
                to: 4000,
                reason: 'You sent 2,000 emails on Dec 7 with 0.5% bounces and 0.02% spam complaints.',
                direction: 'up',
            },
        ],
        broadcast: {
            name: BROADCAST_NAME,
            audience: 25000,
            sentSoFar: 4000,
            plan: [
                { date: 'Today', emails: 4000 },
                { date: 'Dec 11', emails: 8000 },
                { date: 'Dec 12', emails: 13000 },
            ],
            sample: { size: 1250, heldUntil: '09:40', bounceRate: 0.004, verdict: 'passed' },
        },
    },
    'moved-down': {
        key: 'moved-down',
        label: 'Moved down after bad sending',
        domain: DOMAIN,
        allowancePerDay: 4000,
        ceilingPerDay: CEILING,
        tomorrowIfClean: 4000,
        sentToday: 1200,
        queued: 0,
        // The 30-day rates look clean while the 7-day window that decides moves does not.
        rates7d: { bounce: 0.034, complaint: 0.0004, sent: 14100 },
        rates30d: { bounce: 0.011, complaint: 0.0002, sent: 41800 },
        moves: [
            {
                date: 'Nov 24',
                from: 0,
                to: 1000,
                reason: 'Sender verified. Every new sender starts here.',
                direction: 'start',
            },
            {
                date: 'Nov 27',
                from: 1000,
                to: 2000,
                reason: 'You sent 1,000 emails on Nov 26 with 0.2% bounces and no spam complaints.',
                direction: 'up',
            },
            {
                date: 'Dec 1',
                from: 2000,
                to: 4000,
                reason: 'You sent 2,000 emails on Nov 30 with 0.4% bounces and 0.01% spam complaints.',
                direction: 'up',
            },
            {
                date: 'Dec 4',
                from: 4000,
                to: 8000,
                reason: 'You sent 4,000 emails on Dec 3 with 0.5% bounces and 0.02% spam complaints.',
                direction: 'up',
            },
            {
                date: 'Dec 9',
                from: 8000,
                to: 4000,
                reason: '3.4% of emails bounced over the last 7 days, above the 2% limit. Most bounces came from the "Win back old trials" broadcast on Dec 8.',
                direction: 'down',
            },
        ],
        broadcast: {
            name: 'Win back old trials',
            audience: 9000,
            sentSoFar: 450,
            plan: [
                { date: 'Dec 8', emails: 4000 },
                { date: 'Dec 9', emails: 5000 },
            ],
            sample: { size: 450, heldUntil: '11:10', bounceRate: 0.071, verdict: 'stopped' },
        },
    },
    blocked: {
        key: 'blocked',
        label: 'Blocked',
        domain: DOMAIN,
        allowancePerDay: 0,
        ceilingPerDay: CEILING,
        tomorrowIfClean: 0,
        sentToday: 0,
        queued: 7400,
        rates7d: { bounce: 0.052, complaint: 0.0061, sent: 8200 },
        rates30d: { bounce: 0.024, complaint: 0.0019, sent: 21900 },
        moves: [
            {
                date: 'Nov 24',
                from: 0,
                to: 1000,
                reason: 'Sender verified. Every new sender starts here.',
                direction: 'start',
            },
            {
                date: 'Nov 27',
                from: 1000,
                to: 2000,
                reason: 'You sent 1,000 emails on Nov 26 with 0.6% bounces and 0.03% spam complaints.',
                direction: 'up',
            },
            {
                date: 'Dec 6',
                from: 2000,
                to: 1000,
                reason: '2.8% of emails bounced over the last 7 days, above the 2% limit.',
                direction: 'down',
            },
            {
                date: 'Dec 9',
                from: 1000,
                to: 0,
                reason: 'Email sending is paused. 0.61% of emails were marked as spam in the last 7 days, and our email provider paused this sender.',
                direction: 'down',
            },
        ],
        broadcast: {
            name: BROADCAST_NAME,
            audience: 8400,
            sentSoFar: 1000,
            plan: [
                { date: 'Dec 9', emails: 1000 },
                { date: 'Paused', emails: 0 },
            ],
        },
        blockedReason:
            'Our email provider paused sending for this project after 0.61% of emails were marked as spam over the last 7 days.',
    },
}

export interface DomainCheck {
    key: DomainProfileKey
    label: string
    domain: string
    band: DomainBand
    signals: { label: string; ok: boolean | 'warn' | 'unknown'; detail: string }[]
    // null while the sender is on hold.
    startPerDay: number | null
    verdict: string
}

// Variant D: the check reads domain age (RDAP), MX records, other senders in SPF and blocklists. It
// sorts a domain into three bands. A failed lookup never fails setup; it lands in Starter.
export const DOMAIN_CHECKS: Record<DomainProfileKey, DomainCheck> = {
    established: {
        key: 'established',
        label: 'Established',
        domain: 'mail.example.com',
        band: 'Established',
        signals: [
            { label: 'Domain age', ok: true, detail: 'Registered 9 years ago' },
            { label: 'Receives email', ok: true, detail: 'MX records found' },
            { label: 'Already sends email', ok: true, detail: 'SPF names 2 other email services' },
            { label: 'Blocklists', ok: true, detail: 'Not listed' },
        ],
        startPerDay: 10000,
        verdict:
            'This domain has sent email for years, so you start at up to 10,000 emails a day. Your first broadcast goes out as a small sample first, so we can check it before the rest.',
    },
    starter: {
        key: 'starter',
        label: 'Starter',
        domain: 'news.example.org',
        band: 'Starter',
        signals: [
            { label: 'Domain age', ok: 'warn', detail: 'Registered 1 year ago' },
            { label: 'Receives email', ok: true, detail: 'MX records found' },
            { label: 'Already sends email', ok: 'warn', detail: 'No other email services in SPF' },
            { label: 'Blocklists', ok: true, detail: 'Not listed' },
        ],
        startPerDay: 1000,
        verdict:
            'You start at 1,000 emails a day. This grows each day you send without many bounces or spam complaints.',
    },
    'lookup-failed': {
        key: 'lookup-failed',
        label: 'Lookup failed',
        domain: 'shop.example.net',
        band: 'Starter',
        signals: [
            { label: 'Domain age', ok: 'unknown', detail: "Couldn't look up the registration date" },
            { label: 'Receives email', ok: true, detail: 'MX records found' },
            { label: 'Already sends email', ok: true, detail: 'SPF names 1 other email service' },
            { label: 'Blocklists', ok: true, detail: 'Not listed' },
        ],
        startPerDay: 1000,
        verdict:
            "We couldn't check everything, so you start at 1,000 emails a day. This grows each day you send without many bounces or spam complaints.",
    },
    'brand-new': {
        key: 'brand-new',
        label: 'Hold: new domain',
        domain: 'launch.example.net',
        band: 'Hold',
        signals: [
            { label: 'Domain age', ok: false, detail: 'Registered 6 days ago' },
            { label: 'Receives email', ok: 'warn', detail: 'No MX records' },
            { label: 'Already sends email', ok: 'warn', detail: 'No other email services in SPF' },
            { label: 'Blocklists', ok: true, detail: 'Not listed' },
        ],
        startPerDay: null,
        verdict:
            'Inboxes treat domains younger than 30 days as spam, so this domain is on hold until Jan 3. Test emails still work.',
    },
    listed: {
        key: 'listed',
        label: 'Hold: blocklisted',
        domain: 'deals.example.com',
        band: 'Hold',
        signals: [
            { label: 'Domain age', ok: true, detail: 'Registered 4 years ago' },
            { label: 'Receives email', ok: true, detail: 'MX records found' },
            { label: 'Already sends email', ok: true, detail: 'SPF names 1 other email service' },
            { label: 'Blocklists', ok: false, detail: 'Listed on Spamhaus DBL' },
        ],
        startPerDay: null,
        verdict: "This domain is on a spam blocklist, so it's on hold. Ask Spamhaus to delist it, then check again.",
    },
}

export function sendDays(state: SendingState): number {
    return state.broadcast.plan.filter((day) => day.emails > 0).length
}
