/** Scratch prototype data for the v12 experiment list and timeline. All names and dates are invented. Not committed. */

/** The prototype's "now", so every render and screenshot draws the same timeline. */
export const LIST_TODAY = '2026-11-16'

export const LIST_STATUS = {
    draft: 'draft',
    running: 'running',
    paused: 'paused',
    exposureFrozen: 'exposure-frozen',
    complete: 'complete',
} as const
export type ListStatus = (typeof LIST_STATUS)[keyof typeof LIST_STATUS]

export const CONCLUSION = {
    won: 'won',
    lost: 'lost',
    inconclusive: 'inconclusive',
    stoppedEarly: 'stopped-early',
    invalid: 'invalid',
} as const
export type Conclusion = (typeof CONCLUSION)[keyof typeof CONCLUSION]

export interface ListExperiment {
    key: string
    name: string
    description?: string
    flagKey: string
    noCode?: boolean
    legacy?: boolean
    /** The variant rolled out to everyone, when one was shipped. */
    shippedVariant?: string
    tags: string[]
    createdBy: string
    createdAt: string
    startDate?: string
    endDate?: string
    /** When the experiment was paused or its exposure was frozen. */
    haltedAt?: string
    /** Days left from the running time estimate. Zero means the target is reached. */
    remainingDays?: number
    status: ListStatus
    conclusion?: Conclusion
    conclusionComment?: string
    archived?: boolean
}

export const PEOPLE = ['Sam Lee', 'Ana Ruiz', 'Kai Moreno', 'Priya Nair', 'Tom Becker'] as const

export const LIST_EXPERIMENTS: ListExperiment[] = [
    {
        key: 'checkout',
        name: 'New checkout flow',
        description: 'A shorter checkout raises the share of carts that complete.',
        flagKey: 'new-checkout-flow',
        tags: ['checkout', 'revenue'],
        createdBy: 'Sam Lee',
        createdAt: '2026-10-28',
        startDate: '2026-11-03',
        remainingDays: 0,
        status: LIST_STATUS.running,
    },
    {
        key: 'pricing-page',
        name: 'Annual plan first on pricing page',
        description: 'Showing the annual plan first moves more new teams to annual billing.',
        flagKey: 'pricing-annual-first',
        tags: ['pricing', 'revenue'],
        createdBy: 'Ana Ruiz',
        createdAt: '2026-10-20',
        startDate: '2026-10-27',
        remainingDays: 9,
        status: LIST_STATUS.running,
    },
    {
        key: 'onboarding-checklist',
        name: 'Onboarding checklist',
        description: 'A checklist on the first screen helps new users reach their first insight sooner.',
        flagKey: 'onboarding-checklist',
        tags: ['onboarding', 'activation'],
        createdBy: 'Kai Moreno',
        createdAt: '2026-11-02',
        startDate: '2026-11-09',
        remainingDays: 16,
        status: LIST_STATUS.running,
    },
    {
        key: 'hero-copy',
        name: 'Homepage hero copy',
        flagKey: 'homepage-hero-copy',
        noCode: true,
        tags: ['marketing'],
        createdBy: 'Priya Nair',
        createdAt: '2026-10-30',
        startDate: '2026-11-11',
        status: LIST_STATUS.running,
    },
    {
        key: 'search-ranking',
        name: 'Search ranking by recency',
        description: 'Ranking recent items first raises clicks on the first result.',
        flagKey: 'search-recency-ranking',
        tags: ['search'],
        createdBy: 'Tom Becker',
        createdAt: '2026-10-05',
        startDate: '2026-10-12',
        haltedAt: '2026-11-04',
        status: LIST_STATUS.paused,
    },
    {
        key: 'email-digest',
        name: 'Weekly email digest',
        description: 'A weekly digest brings inactive users back.',
        flagKey: 'weekly-digest',
        tags: ['retention', 'email'],
        createdBy: 'Ana Ruiz',
        createdAt: '2026-09-22',
        startDate: '2026-10-01',
        haltedAt: '2026-11-01',
        remainingDays: 6,
        status: LIST_STATUS.exposureFrozen,
    },
    {
        key: 'trial-length',
        name: 'Trial length 14 to 30 days',
        description: 'A longer trial raises paid conversion.',
        flagKey: 'trial-length-30',
        shippedVariant: 'thirty-days',
        tags: ['pricing', 'activation'],
        createdBy: 'Sam Lee',
        createdAt: '2026-08-18',
        startDate: '2026-08-25',
        endDate: '2026-10-06',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.won,
        conclusionComment: 'Paid conversion up 6% with no change in churn.',
    },
    {
        key: 'nav-labels',
        name: 'Navigation labels',
        flagKey: 'nav-labels',
        tags: ['navigation'],
        createdBy: 'Kai Moreno',
        createdAt: '2026-09-01',
        startDate: '2026-09-08',
        endDate: '2026-10-20',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.inconclusive,
        conclusionComment: 'No difference in task success after six weeks.',
    },
    {
        key: 'cart-upsell',
        name: 'Cart upsell banner',
        description: 'A related item banner in the cart raises order value.',
        flagKey: 'cart-upsell-banner',
        tags: ['checkout', 'revenue'],
        createdBy: 'Priya Nair',
        createdAt: '2026-09-10',
        startDate: '2026-09-15',
        endDate: '2026-10-13',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.lost,
        conclusionComment: 'Order value flat and cart abandonment up 3%.',
    },
    {
        key: 'signup-sso',
        name: 'SSO first on sign up',
        flagKey: 'signup-sso-first',
        tags: ['onboarding'],
        createdBy: 'Tom Becker',
        createdAt: '2026-10-01',
        startDate: '2026-10-06',
        endDate: '2026-10-16',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.stoppedEarly,
        conclusionComment: 'Stopped after a login bug on one provider.',
    },
    {
        key: 'dark-mode-default',
        name: 'Dark mode by default',
        flagKey: 'dark-mode-default',
        legacy: true,
        tags: ['ui'],
        createdBy: 'Sam Lee',
        createdAt: '2026-06-30',
        startDate: '2026-07-06',
        endDate: '2026-08-17',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.invalid,
    },
    {
        key: 'referral-reward',
        name: 'Referral reward size',
        description: 'A larger reward brings more referrals per active user.',
        flagKey: 'referral-reward',
        tags: ['growth'],
        createdBy: 'Ana Ruiz',
        createdAt: '2026-11-12',
        status: LIST_STATUS.draft,
    },
    {
        key: 'mobile-tabbar',
        name: 'Mobile tab bar',
        flagKey: 'mobile-tab-bar',
        tags: ['navigation', 'mobile'],
        createdBy: 'Kai Moreno',
        createdAt: '2026-11-14',
        status: LIST_STATUS.draft,
    },
    {
        key: 'faq-chat',
        name: 'FAQ chat widget',
        flagKey: 'faq-chat-widget',
        tags: ['support'],
        createdBy: 'Priya Nair',
        createdAt: '2026-07-14',
        startDate: '2026-07-20',
        endDate: '2026-08-31',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.won,
        archived: true,
    },
]

export const ALL_TAGS = [...new Set(LIST_EXPERIMENTS.flatMap((experiment) => experiment.tags))].sort()

export interface Velocity {
    launched: number
    /** Percent change in launches against the 30 days before. */
    launchedChange: number
    running: number
    completed: number
}

/** Fake numbers for the velocity stats, to match the list above. */
export const VELOCITY: Velocity = { launched: 4, launchedChange: 33, running: 4, completed: 3 }

export const VELOCITY_DOWN: Velocity = { launched: 5, launchedChange: -29, running: 3, completed: 6 }

export const VELOCITY_FLAT: Velocity = { launched: 6, launchedChange: 0, running: 5, completed: 2 }

export const VELOCITY_LOW: Velocity = { launched: 2, launchedChange: -50, running: 1, completed: 1 }

/** v17 adds older experiments, so the timeline has history to scroll back through. Earlier rounds keep the list above. */
export const LIST_EXPERIMENTS_V17: ListExperiment[] = [
    ...LIST_EXPERIMENTS,
    {
        key: 'recommendations',
        name: 'Recommendations carousel',
        description: 'A carousel of related items on the product page raises items per order.',
        flagKey: 'recommendations-carousel',
        tags: ['revenue'],
        createdBy: 'Kai Moreno',
        createdAt: '2026-06-15',
        startDate: '2026-06-22',
        endDate: '2026-09-07',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.won,
        conclusionComment: 'Items per order up 4% with no change in returns.',
    },
    {
        key: 'pricing-table',
        name: 'Pricing table layout',
        flagKey: 'pricing-table-layout',
        tags: ['pricing'],
        createdBy: 'Ana Ruiz',
        createdAt: '2026-03-30',
        startDate: '2026-04-06',
        endDate: '2026-05-18',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.won,
        conclusionComment: 'More teams picked the middle plan.',
    },
    {
        key: 'search-autocomplete',
        name: 'Search autocomplete',
        flagKey: 'search-autocomplete',
        tags: ['search'],
        createdBy: 'Tom Becker',
        createdAt: '2026-04-27',
        startDate: '2026-05-04',
        endDate: '2026-06-15',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.inconclusive,
    },
    {
        key: 'onboarding-video',
        name: 'Onboarding video',
        flagKey: 'onboarding-video',
        tags: ['onboarding'],
        createdBy: 'Priya Nair',
        createdAt: '2026-05-25',
        startDate: '2026-06-01',
        endDate: '2026-07-13',
        status: LIST_STATUS.complete,
        conclusion: CONCLUSION.lost,
        conclusionComment: 'Fewer users finished onboarding.',
    },
]
