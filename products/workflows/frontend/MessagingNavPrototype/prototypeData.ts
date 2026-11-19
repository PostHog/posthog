// PROTOTYPE, never merged: PostHog/michaelr-context#419. Invented data, no real customers or numbers.

export interface PrototypeBroadcast {
    id: string
    name: string
    status: 'Draft' | 'Scheduled' | 'Sent'
    audience: string
    when: string
    recipients: number | null
}

export interface PrototypeTransactionalEmail {
    id: string
    name: string
    slug: string
    sent7d: number
    lastSent: string
}

export interface PrototypeWorkflow {
    id: string
    name: string
    status: 'Live' | 'Draft' | 'Archived'
    trigger: string
    channels: string[]
    kind: 'Messaging' | 'Automation' | 'Loop'
}

export interface PrototypeTemplate {
    id: string
    name: string
    transactional: boolean
    updated: string
}

export const PROTOTYPE_BROADCASTS: PrototypeBroadcast[] = [
    {
        id: 'b1',
        name: 'November product update',
        status: 'Scheduled',
        audience: 'All active users',
        when: 'Thu 21 Nov, 10:00',
        recipients: null,
    },
    {
        id: 'b2',
        name: 'Webinar reminder: data pipelines',
        status: 'Scheduled',
        audience: 'Webinar sign-ups',
        when: 'Mon 25 Nov, 15:00',
        recipients: null,
    },
    {
        id: 'b3',
        name: 'Holiday pricing announcement',
        status: 'Draft',
        audience: 'Paying customers',
        when: 'Not scheduled',
        recipients: null,
    },
    {
        id: 'b4',
        name: 'October product update',
        status: 'Sent',
        audience: 'All active users',
        when: '17 Oct',
        recipients: 12480,
    },
    {
        id: 'b5',
        name: 'Beta invite: new editor',
        status: 'Sent',
        audience: 'Beta testers',
        when: '2 Oct',
        recipients: 312,
    },
]

export const PROTOTYPE_TRANSACTIONAL: PrototypeTransactionalEmail[] = [
    { id: 't1', name: 'Password reset', slug: 'password-reset', sent7d: 1840, lastSent: '2 min ago' },
    { id: 't2', name: 'Welcome email', slug: 'welcome', sent7d: 920, lastSent: '14 min ago' },
    { id: 't3', name: 'Invoice receipt', slug: 'invoice-receipt', sent7d: 410, lastSent: '1 hour ago' },
    { id: 't4', name: 'Invite a teammate', slug: 'team-invite', sent7d: 96, lastSent: 'Yesterday' },
]

export const PROTOTYPE_WORKFLOWS: PrototypeWorkflow[] = [
    {
        id: 'w1',
        name: 'Onboarding drip',
        status: 'Live',
        trigger: 'User signed up',
        channels: ['Email'],
        kind: 'Messaging',
    },
    {
        id: 'w2',
        name: 'Trial ending reminder',
        status: 'Live',
        trigger: 'Trial ends in 3 days',
        channels: ['Email', 'Slack'],
        kind: 'Messaging',
    },
    {
        id: 'w3',
        name: 'Win back inactive users',
        status: 'Live',
        trigger: 'Inactive for 30 days',
        channels: ['Email', 'Push'],
        kind: 'Messaging',
    },
    {
        id: 'w4',
        name: 'Order shipped SMS',
        status: 'Live',
        trigger: 'Order shipped',
        channels: ['SMS'],
        kind: 'Messaging',
    },
    {
        id: 'w5',
        name: 'NPS follow-up',
        status: 'Live',
        trigger: 'Survey sent',
        channels: ['Email'],
        kind: 'Messaging',
    },
    {
        id: 'w6',
        name: 'Feature adoption nudge',
        status: 'Draft',
        trigger: 'Feature not used in 7 days',
        channels: ['Email'],
        kind: 'Messaging',
    },
    {
        id: 'w7',
        name: 'Sync new signups to CRM',
        status: 'Live',
        trigger: 'User signed up',
        channels: ['Webhook'],
        kind: 'Automation',
    },
    {
        id: 'w8',
        name: 'Alert sales on big accounts',
        status: 'Live',
        trigger: 'Account crossed 50 seats',
        channels: ['Slack'],
        kind: 'Automation',
    },
    {
        id: 'w9',
        name: 'Tag churn risk',
        status: 'Live',
        trigger: 'Usage dropped 50%',
        channels: ['Update person'],
        kind: 'Loop',
    },
]

export const PROTOTYPE_TEMPLATES: PrototypeTemplate[] = [
    { id: 'tp1', name: 'Product update', transactional: false, updated: '3 days ago' },
    { id: 'tp2', name: 'Password reset', transactional: true, updated: '2 weeks ago' },
    { id: 'tp3', name: 'Welcome email', transactional: true, updated: '1 month ago' },
    { id: 'tp4', name: 'Event invitation', transactional: false, updated: '1 month ago' },
]

export const PROTOTYPE_SENDING_DOMAIN = 'mail.example.com'
