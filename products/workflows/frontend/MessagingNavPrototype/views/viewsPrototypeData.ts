// PROTOTYPE, never merged: PostHog/michaelr-context#421. Invented data, no real customers or numbers.

export type MessageType = 'broadcast' | 'transactional' | 'workflow'
export type MessageStatus = 'Draft' | 'Scheduled' | 'Sent' | 'Live' | 'Archived'

export interface MessageItem {
    id: string
    type: MessageType
    name: string
    status: MessageStatus
    tags: string[]
    createdBy: string
    /** Display text, plus a rank so sorting by it works. */
    updated: string
    updatedRank: number
    when?: string
    whenRank?: number
    recipients?: number | null
    slug?: string
    sent7d?: number
    trigger?: string
    channels?: string[]
}

export const ME = 'Alex Example'
export const PEOPLE = [ME, 'Sam Example', 'Kim Example']

export const TYPE_LABELS: Record<MessageType, string> = {
    broadcast: 'Broadcast',
    transactional: 'Transactional email',
    workflow: 'Messaging workflow',
}

export const TYPE_PLURALS: Record<MessageType, string> = {
    broadcast: 'broadcasts',
    transactional: 'transactional emails',
    workflow: 'messaging workflows',
}

export const STATUSES_BY_TYPE: Record<MessageType, MessageStatus[]> = {
    broadcast: ['Draft', 'Scheduled', 'Sent', 'Archived'],
    transactional: ['Live', 'Draft'],
    workflow: ['Live', 'Draft', 'Archived'],
}

const b = (
    id: string,
    name: string,
    status: MessageStatus,
    tags: string[],
    createdBy: string,
    when: string,
    whenRank: number,
    recipients: number | null
): MessageItem => ({
    id,
    type: 'broadcast',
    name,
    status,
    tags,
    createdBy,
    when,
    whenRank,
    recipients,
    updated: when,
    updatedRank: whenRank,
})

const t = (
    id: string,
    name: string,
    slug: string,
    status: MessageStatus,
    tags: string[],
    createdBy: string,
    sent7d: number,
    updated: string,
    updatedRank: number
): MessageItem => ({ id, type: 'transactional', name, slug, status, tags, createdBy, sent7d, updated, updatedRank })

const w = (
    id: string,
    name: string,
    status: MessageStatus,
    tags: string[],
    createdBy: string,
    trigger: string,
    channels: string[],
    updated: string,
    updatedRank: number
): MessageItem => ({ id, type: 'workflow', name, status, tags, createdBy, trigger, channels, updated, updatedRank })

export const MESSAGE_ITEMS: MessageItem[] = [
    b('b1', 'November product update', 'Scheduled', ['product-updates'], ME, 'Thu 21 Nov, 10:00', 21, null),
    b('b2', 'Webinar reminder: data pipelines', 'Scheduled', ['events'], 'Sam Example', 'Mon 25 Nov, 15:00', 25, null),
    b('b3', 'Holiday pricing announcement', 'Draft', ['billing'], ME, 'Not scheduled', 99, null),
    b('b4', 'Welcome to the beta', 'Draft', ['onboarding'], 'Kim Example', 'Not scheduled', 98, null),
    b('b5', 'October product update', 'Sent', ['product-updates'], ME, '17 Oct', -33, 12480),
    b('b6', 'Beta invite: new editor', 'Sent', ['onboarding', 'product-updates'], 'Sam Example', '2 Oct', -48, 312),
    b('b7', 'Security notice: new sign-in rules', 'Sent', ['security'], 'Kim Example', '24 Sep', -56, 11930),
    b('b8', 'Summer event recap', 'Archived', ['events'], ME, '12 Aug', -99, 2210),
    t('t1', 'Password reset', 'password-reset', 'Live', ['security'], 'Kim Example', 1840, '2 weeks ago', -14),
    t('t2', 'Welcome email', 'welcome', 'Live', ['onboarding'], ME, 920, '1 month ago', -30),
    t('t3', 'Invoice receipt', 'invoice-receipt', 'Live', ['billing'], 'Sam Example', 410, '3 days ago', -3),
    t('t4', 'Invite a teammate', 'team-invite', 'Live', ['onboarding'], ME, 96, '1 month ago', -31),
    t('t5', 'Payment failed', 'payment-failed', 'Live', ['billing'], 'Sam Example', 58, '5 days ago', -5),
    t('t6', 'Verify your email', 'verify-email', 'Draft', ['onboarding', 'security'], ME, 0, 'Yesterday', -1),
    w('w1', 'Onboarding drip', 'Live', ['onboarding', 'lifecycle'], ME, 'User signed up', ['Email'], '2 days ago', -2),
    w(
        'w2',
        'Trial ending reminder',
        'Live',
        ['billing', 'lifecycle'],
        'Sam Example',
        'Trial ends in 3 days',
        ['Email', 'Slack'],
        '1 week ago',
        -7
    ),
    w(
        'w3',
        'Win back inactive users',
        'Live',
        ['lifecycle'],
        'Kim Example',
        'Inactive for 30 days',
        ['Email', 'Push'],
        '3 weeks ago',
        -21
    ),
    w('w4', 'Order shipped SMS', 'Live', [], 'Sam Example', 'Order shipped', ['SMS'], '1 month ago', -30),
    w('w5', 'NPS follow-up', 'Live', ['lifecycle'], ME, 'Survey sent', ['Email'], '2 months ago', -60),
    w('w6', 'Feature adoption nudge', 'Draft', ['onboarding'], ME, 'Feature not used in 7 days', ['Email'], 'Today', 0),
    w(
        'w7',
        'Event follow-up',
        'Archived',
        ['events'],
        'Kim Example',
        'Event attended',
        ['Email'],
        '4 months ago',
        -120
    ),
]

export const ALL_TAGS = Array.from(new Set(MESSAGE_ITEMS.flatMap((item) => item.tags))).sort()
