import { OriginProduct } from './types'

// Origin product display constants
export const ORIGIN_PRODUCT_LABELS: Record<OriginProduct, string> = {
    [OriginProduct.ERROR_TRACKING]: 'Error Tracking',
    [OriginProduct.EVAL_CLUSTERS]: 'Eval Clusters',
    [OriginProduct.USER_CREATED]: 'User Created',
    [OriginProduct.SUPPORT_QUEUE]: 'Support Queue',
    [OriginProduct.SESSION_SUMMARIES]: 'Session Summaries',
}

export const ORIGIN_PRODUCT_COLORS: Record<OriginProduct, string> = {
    [OriginProduct.ERROR_TRACKING]: 'bg-red-100 text-red-800',
    [OriginProduct.EVAL_CLUSTERS]: 'bg-sky-100 text-sky-800',
    [OriginProduct.USER_CREATED]: 'bg-emerald-100 text-emerald-800',
    [OriginProduct.SUPPORT_QUEUE]: 'bg-orange-100 text-orange-800',
    [OriginProduct.SESSION_SUMMARIES]: 'bg-purple-100 text-purple-800',
}

// Agent definitions
export const AGENTS = [
    {
        id: 'code_generation',
        name: 'Code Generation Agent',
        agent_type: 'code_generation',
        description: 'Automated code generation and GitHub integration',
        config: {},
        is_active: true,
    },
    {
        id: 'triage',
        name: 'Triage Agent',
        agent_type: 'triage',
        description: 'Automatically triages and categorizes tasks based on content',
        config: {},
        is_active: true,
    },
    {
        id: 'review',
        name: 'Review Agent',
        agent_type: 'review',
        description: 'Reviews code changes and provides automated feedback',
        config: {},
        is_active: true,
    },
    {
        id: 'testing',
        name: 'Testing Agent',
        agent_type: 'testing',
        description: 'Runs tests and validates implementation',
        config: {},
        is_active: true,
    },
]

export const AGENTS_BY_ID = Object.fromEntries(AGENTS.map((agent) => [agent.id, agent]))
