/**
 * Progressive disclosure taxonomy: groups the MCP's ~200+ tools into a small set of
 * product-shaped toolsets. In progressive mode (`?progressive=true`), only the bootstrap
 * tools are surfaced initially; the rest activate when a model calls
 * `toolsets(action='enable', name='<id>')`.
 *
 * Product-shaped rather than workflow-shaped so the groups align with how the underlying
 * features ship — a new `notebooks` agentic feature can split out of `content` without
 * breaking skills that declared `required_toolsets: ['analytics']`.
 */

export type ToolsetId =
    | 'analytics'
    | 'content'
    | 'flags'
    | 'experiments'
    | 'surveys'
    | 'error_tracking'
    | 'llm_analytics'
    | 'workspace'
    | 'data_warehouse'
    | 'replay'
    | 'hog_functions'
    | 'logs'
    | 'workflows'
    | 'reverse_proxy'

export type ToolsetDefinition = {
    id: ToolsetId
    title: string
    description: string
    /** Tool-definition `feature` values that belong to this toolset. */
    features: string[]
}

/**
 * Tools always available in progressive mode regardless of which toolsets are enabled.
 * Kept small (goal: ≤5 from the RFC) so idle token cost stays near the 5K target.
 */
export const BOOTSTRAP_TOOL_NAMES = ['query-run', 'docs-search', 'entity-search', 'toolsets'] as const

export const TOOLSETS: ToolsetDefinition[] = [
    {
        id: 'analytics',
        title: 'Analytics',
        description:
            'Events, insights, cohorts, actions, persons, and product analytics. Enable for trends, funnels, retention, HogQL, insight CRUD, and event/property discovery.',
        features: ['insights', 'events', 'product_analytics', 'cohorts', 'actions', 'persons'],
    },
    {
        id: 'content',
        title: 'Dashboards, notebooks, annotations',
        description:
            'Dashboards, notebooks, and annotations. Enable for dashboard CRUD, notebook reads/writes, and annotating charts.',
        features: ['dashboards', 'notebooks', 'annotations'],
    },
    {
        id: 'flags',
        title: 'Feature flags',
        description:
            'Feature flag CRUD + early access features. Enable for flag definitions, rollout changes, and release gating.',
        features: ['flags', 'early_access_features'],
    },
    {
        id: 'experiments',
        title: 'Experiments',
        description: 'A/B experiments and results. Enable for experiment CRUD and result reads.',
        features: ['experiments'],
    },
    {
        id: 'surveys',
        title: 'Surveys',
        description: 'Survey CRUD and stats. Enable for survey management and response analytics.',
        features: ['surveys'],
    },
    {
        id: 'error_tracking',
        title: 'Error tracking',
        description: 'Exceptions and error issues. Enable for exception triage and error investigation.',
        features: ['error_tracking'],
    },
    {
        id: 'llm_analytics',
        title: 'LLM analytics',
        description:
            'LLM traces, prompts, evaluations, conversations, and cost. Enable when the user asks about LLM spend, prompt versioning, or tracing.',
        features: ['llm_analytics', 'prompts', 'conversations'],
    },
    {
        id: 'workspace',
        title: 'Workspace',
        description:
            'Orgs, projects, platform admin, integrations, alerts, roles. Enable first if the model cannot tell which project to query or needs admin primitives.',
        features: ['workspace', 'core', 'platform_features', 'integrations', 'alerts'],
    },
    {
        id: 'data_warehouse',
        title: 'Data warehouse + endpoints',
        description:
            'Warehouse views, endpoints, SQL, and data schema. Enable for warehouse queries, query endpoints, and exploring the schema.',
        features: ['data_warehouse', 'endpoints', 'data_schema', 'sql'],
    },
    {
        id: 'replay',
        title: 'Session replay',
        description: 'Recordings and playlists. Enable for session recording reads and playlist management.',
        features: ['replay'],
    },
    {
        id: 'hog_functions',
        title: 'Destinations / Hog functions',
        description: 'CDP destinations, sources, transformations, and Hog function templates.',
        features: ['hog_functions', 'hog_function_templates'],
    },
    {
        id: 'logs',
        title: 'Logs',
        description: 'Log queries and log attribute discovery.',
        features: ['logs'],
    },
    {
        id: 'workflows',
        title: 'Workflows',
        description: 'Workflow CRUD. Enable when the user asks about automation workflows.',
        features: ['workflows'],
    },
    {
        id: 'reverse_proxy',
        title: 'Managed reverse proxy',
        description: 'PostHog managed reverse proxy CRUD.',
        features: ['reverse_proxy'],
    },
]

const FEATURE_TO_TOOLSET: Record<string, ToolsetId> = (() => {
    const out: Record<string, ToolsetId> = {}
    for (const ts of TOOLSETS) {
        for (const feature of ts.features) {
            out[feature] = ts.id
        }
    }
    return out
})()

export function toolsetIdForFeature(feature: string): ToolsetId | undefined {
    return FEATURE_TO_TOOLSET[feature]
}

export function getToolsetById(id: string): ToolsetDefinition | undefined {
    return TOOLSETS.find((ts) => ts.id === id)
}

export function isBootstrapTool(name: string): boolean {
    return (BOOTSTRAP_TOOL_NAMES as readonly string[]).includes(name)
}

export function isValidToolsetId(id: string): id is ToolsetId {
    return TOOLSETS.some((ts) => ts.id === id)
}
