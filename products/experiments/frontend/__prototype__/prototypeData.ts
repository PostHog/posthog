/** Scratch prototype data. Invented values only; not committed. */

export const PROTOTYPE_STATUS = {
    draft: 'draft',
    running: 'running',
    paused: 'paused',
    complete: 'complete',
} as const
export type PrototypeStatus = (typeof PROTOTYPE_STATUS)[keyof typeof PROTOTYPE_STATUS]

export interface PrototypeVariantResult {
    key: string
    value: string
    detail: string
    /** Relative delta vs control, as a fraction; null for control. */
    delta: number | null
    interval: [number, number] | null
    chanceToWin: number | null
}

export const METRIC_GOAL = { increase: 'increase', decrease: 'decrease' } as const
export type MetricGoal = (typeof METRIC_GOAL)[keyof typeof METRIC_GOAL]

export interface PrototypeMetric {
    name: string
    kind: 'Funnel' | 'Mean' | 'Ratio'
    /** Which direction counts as a win. Missing means increase, as in the product. */
    goal?: MetricGoal
    variants: PrototypeVariantResult[]
}

export const VARIANTS = ['control', 'compact-cart', 'one-page'] as const

export const EXPERIMENT = {
    name: 'New checkout flow',
    flagKey: 'new-checkout-flow',
    hypothesis:
        'A one-page checkout removes two steps, so more people who start checkout will finish it. We expect at least a 5% lift in completed checkouts.',
    statsMethod: 'Bayesian',
    confidence: '95%',
    startDate: 'Nov 3, 2026',
    endDate: 'Nov 16, 2026',
    owner: 'Sam Lee',
    ownerInitial: 'S',
}

export const PRIMARY_METRICS: PrototypeMetric[] = [
    {
        name: 'Checkout completed',
        kind: 'Funnel',
        variants: [
            {
                key: 'control',
                value: '41.2%',
                detail: '1,712 / 4,155',
                delta: null,
                interval: null,
                chanceToWin: null,
            },
            {
                key: 'compact-cart',
                value: '42.6%',
                detail: '1,781 / 4,181',
                delta: 0.034,
                interval: [-0.021, 0.089],
                chanceToWin: 0.88,
            },
            {
                key: 'one-page',
                value: '44.7%',
                detail: '1,849 / 4,144',
                delta: 0.084,
                interval: [0.031, 0.139],
                chanceToWin: 0.99,
            },
        ],
    },
    {
        name: 'Revenue per user',
        kind: 'Mean',
        variants: [
            { key: 'control', value: '$18.40', detail: '4,155 users', delta: null, interval: null, chanceToWin: null },
            {
                key: 'compact-cart',
                value: '$18.71',
                detail: '4,181 users',
                delta: 0.017,
                interval: [-0.038, 0.072],
                chanceToWin: 0.72,
            },
            {
                key: 'one-page',
                value: '$19.20',
                detail: '4,144 users',
                delta: 0.043,
                interval: [-0.012, 0.098],
                chanceToWin: 0.93,
            },
        ],
    },
    {
        name: 'Items per order',
        kind: 'Ratio',
        variants: [
            { key: 'control', value: '2.31', detail: '3,955 / 1,712', delta: null, interval: null, chanceToWin: null },
            {
                key: 'compact-cart',
                value: '2.19',
                detail: '3,900 / 1,781',
                delta: -0.052,
                interval: [-0.094, -0.01],
                chanceToWin: 0.01,
            },
            {
                key: 'one-page',
                value: '2.28',
                detail: '4,216 / 1,849',
                delta: -0.013,
                interval: [-0.056, 0.03],
                chanceToWin: 0.27,
            },
        ],
    },
]

export const SECONDARY_METRICS: PrototypeMetric[] = [
    {
        name: 'Support ticket opened',
        kind: 'Funnel',
        variants: [
            { key: 'control', value: '1.9%', detail: '79 / 4,155', delta: null, interval: null, chanceToWin: null },
            {
                key: 'compact-cart',
                value: '2.0%',
                detail: '84 / 4,181',
                delta: 0.05,
                interval: [-0.24, 0.34],
                chanceToWin: 0.61,
            },
            {
                key: 'one-page',
                value: '1.7%',
                detail: '70 / 4,144',
                delta: -0.11,
                interval: [-0.38, 0.16],
                chanceToWin: 0.22,
            },
        ],
    },
    {
        name: 'Payment error shown',
        kind: 'Funnel',
        variants: [
            { key: 'control', value: '3.1%', detail: '129 / 4,155', delta: null, interval: null, chanceToWin: null },
            {
                key: 'compact-cart',
                value: '3.0%',
                detail: '125 / 4,181',
                delta: -0.03,
                interval: [-0.26, 0.2],
                chanceToWin: 0.41,
            },
            {
                key: 'one-page',
                value: '3.4%',
                detail: '141 / 4,144',
                delta: 0.1,
                interval: [-0.12, 0.32],
                chanceToWin: 0.8,
            },
        ],
    },
]

export const EXPOSURES = {
    total: '12,480',
    split: [
        { key: 'control', count: '4,155', share: '33.3%' },
        { key: 'compact-cart', count: '4,181', share: '33.5%' },
        { key: 'one-page', count: '4,144', share: '33.2%' },
    ],
    criteria: 'Default ($feature_flag_called)',
    days: [
        '2026-11-03',
        '2026-11-04',
        '2026-11-05',
        '2026-11-06',
        '2026-11-07',
        '2026-11-08',
        '2026-11-09',
        '2026-11-10',
        '2026-11-11',
        '2026-11-12',
        '2026-11-13',
        '2026-11-14',
        '2026-11-15',
        '2026-11-16',
    ],
    daily: {
        control: [310, 330, 345, 320, 300, 180, 330, 340, 350, 335, 300, 275, 270, 245],
        'compact-cart': [305, 343, 350, 330, 295, 177, 339, 345, 350, 340, 310, 271, 272, 254],
        'one-page': [312, 324, 340, 322, 297, 179, 341, 339, 352, 336, 311, 269, 269, 253],
    } as Record<string, number[]>,
}

export const HEALTH_ISSUES = [
    {
        severity: 'warning' as const,
        title: 'Exposures dropped on Nov 8',
        detail: 'Exposures fell 40% for one day. Check the flag was evaluated.',
    },
    {
        severity: 'warning' as const,
        title: '2% of users saw more than one variant',
        detail: 'They are excluded from the results.',
    },
]
