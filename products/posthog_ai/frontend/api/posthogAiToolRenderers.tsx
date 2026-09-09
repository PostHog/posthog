import {
    IconDashboard,
    IconFunnels,
    IconGraph,
    IconLifecycle,
    IconLlmAnalytics,
    IconNotebook,
    IconPerson,
    IconRetention,
    IconRewindPlay,
    IconStickiness,
    IconTrends,
    IconUserPaths,
    IconWarning,
} from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ToolRegistryEntry } from './tools'

// Lazy factories keep widget implementations out of the registry's eager import graph.
const InsightRenderer = lazyWithRetry(() =>
    import('../components/tool/widgets/CreateInsightWidget').then((m) => ({ default: m.CreateInsightWidget }))
)
const DashboardRenderer = lazyWithRetry(() =>
    import('../components/tool/widgets/UpsertDashboardWidget').then((m) => ({ default: m.UpsertDashboardWidget }))
)
const SessionRecordingsRenderer = lazyWithRetry(() =>
    import('../components/tool/widgets/SearchSessionRecordingsWidget').then((m) => ({
        default: m.SearchSessionRecordingsWidget,
    }))
)
const ErrorTrackingRenderer = lazyWithRetry(() =>
    import('../components/tool/widgets/ErrorTrackingWidget').then((m) => ({ default: m.ErrorTrackingWidget }))
)
const NotebookRenderer = lazyWithRetry(() =>
    import('../components/tool/widgets/CreateNotebookWidget').then((m) => ({ default: m.CreateNotebookWidget }))
)
const QueryRenderer = lazyWithRetry(() =>
    import('../components/tool/widgets/QueryWidget').then((m) => ({ default: m.QueryWidget }))
)

const DATA_TOOLS = [
    {
        keys: ['insight-create', 'insight-update', 'insight-get', 'create_insight'],
        displayName: 'Insight',
        icon: <IconGraph />,
        Renderer: InsightRenderer,
    },

    {
        keys: ['dashboard-create', 'dashboard-update', 'upsert_dashboard'],
        displayName: 'Dashboard',
        icon: <IconDashboard />,
        Renderer: DashboardRenderer,
    },

    {
        keys: ['query-session-recordings-list', 'search_session_recordings', 'filter_session_recordings'],
        displayName: 'Session recordings',
        icon: <IconRewindPlay />,
        Renderer: SessionRecordingsRenderer,
    },

    {
        keys: [
            'query-error-tracking-issues-list',
            'query-error-tracking-issue',
            'query-error-tracking-issue-events',
            'search_error_tracking_issues',
            'filter_error_tracking_issues',
        ],
        displayName: 'Error tracking',
        icon: <IconWarning />,
        Renderer: ErrorTrackingRenderer,
    },

    // The generated CRUD tools and the handwritten notebook-edit (the collab-safe content editor) all
    // return the same REST notebook payload. A feature flag swaps that set for the markdown notebook
    // tools, so both sets are registered — a thread only ever contains calls from the set its own run
    // was served. The cell tools (add / update / delete) stay on the generic card: they return a cell
    // run, not a notebook, so this card has nothing to show for them.
    {
        keys: [
            'notebooks-create',
            'notebooks-partial-update',
            'notebooks-retrieve',
            'notebook-edit',
            'notebooks-create-markdown',
            'notebooks-get',
        ],
        displayName: 'Notebook',
        icon: <IconNotebook />,
        Renderer: NotebookRenderer,
    },
]

const QUERY_WRAPPER_TOOLS: { key: string; displayName: string; icon: JSX.Element }[] = [
    { key: 'query-trends', displayName: 'Trends query', icon: <IconTrends /> },
    { key: 'query-funnel', displayName: 'Funnel query', icon: <IconFunnels /> },
    { key: 'query-retention', displayName: 'Retention query', icon: <IconRetention /> },
    { key: 'query-stickiness', displayName: 'Stickiness query', icon: <IconStickiness /> },
    { key: 'query-paths', displayName: 'Paths query', icon: <IconUserPaths /> },
    { key: 'query-lifecycle', displayName: 'Lifecycle query', icon: <IconLifecycle /> },
    { key: 'query-llm-traces-list', displayName: 'LLM traces', icon: <IconLlmAnalytics /> },
    { key: 'query-trends-actors', displayName: 'Trends persons', icon: <IconPerson /> },
    { key: 'query-lifecycle-actors', displayName: 'Lifecycle persons', icon: <IconPerson /> },
    { key: 'query-paths-actors', displayName: 'Paths persons', icon: <IconPerson /> },
]
export const posthogAiToolRenderers: ToolRegistryEntry[] = [
    ...DATA_TOOLS.flatMap(({ keys, ...entry }) =>
        keys.map((key) => ({ key, ...entry, requiresPostHogOrigin: true, keepVisible: true }))
    ),
    ...QUERY_WRAPPER_TOOLS.map((entry) => ({ ...entry, Renderer: QueryRenderer, requiresPostHogOrigin: true, keepVisible: true })),
]
