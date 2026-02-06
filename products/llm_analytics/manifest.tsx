import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'LLM Analytics',
    scenes: {
        LLMAnalytics: {
            import: () => import('./frontend/LLMAnalyticsScene'),
            projectBased: true,
            name: 'LLM analytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
            description: 'Analyze and understand your LLM usage and performance.',
            iconType: 'llm_analytics',
        },
        LLMAnalyticsTrace: {
            import: () => import('./frontend/LLMAnalyticsTraceScene'),
            projectBased: true,
            name: 'LLM analytics trace',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/traces',
        },
        LLMAnalyticsSession: {
            import: () => import('./frontend/LLMAnalyticsSessionScene'),
            projectBased: true,
            name: 'LLM analytics session',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/sessions',
        },
        LLMAnalyticsUsers: {
            import: () => import('./frontend/LLMAnalyticsUsers'),
            projectBased: true,
            name: 'LLM analytics users',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsPlayground: {
            import: () => import('./frontend/LLMAnalyticsPlaygroundScene'),
            projectBased: true,
            name: 'LLM playground',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsDatasets: {
            import: () => import('./frontend/datasets/LLMAnalyticsDatasetsScene'),
            projectBased: true,
            name: 'LLM analytics datasets',
            description: 'Manage datasets for testing and evaluation.',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsDataset: {
            import: () => import('./frontend/datasets/LLMAnalyticsDatasetScene'),
            projectBased: true,
            name: 'LLM analytics dataset',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsEvaluations: {
            import: () => import('./frontend/evaluations/LLMAnalyticsEvaluationsScene'),
            projectBased: true,
            name: 'Evaluations',
            description: 'Configure and monitor automated LLM output evaluations.',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/evaluations',
        },
        LLMAnalyticsEvaluation: {
            import: () => import('./frontend/evaluations/LLMAnalyticsEvaluation'),
            projectBased: true,
            name: 'LLM analytics evaluation',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsEvaluationTemplates: {
            import: () => import('./frontend/evaluations/EvaluationTemplates'),
            projectBased: true,
            name: 'LLM analytics evaluation templates',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsPrompts: {
            import: () => import('./frontend/prompts/LLMPromptsScene'),
            projectBased: true,
            name: 'Prompts',
            description: 'Track and manage your LLM prompts.',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/prompts',
        },
        LLMAnalyticsPrompt: {
            import: () => import('./frontend/prompts/LLMPromptScene'),
            projectBased: true,
            name: 'LLM analytics prompt',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsClusters: {
            import: () => import('./frontend/clusters/LLMAnalyticsClustersScene'),
            projectBased: true,
            name: 'Clusters',
            description: 'Discover patterns and clusters in your LLM usage.',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/clusters',
        },
        LLMAnalyticsCluster: {
            import: () => import('./frontend/clusters/LLMAnalyticsClusterScene'),
            projectBased: true,
            name: 'LLM analytics cluster',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
    },
    routes: {
        '/llm-analytics/dashboard': ['LLMAnalytics', 'llmAnalyticsDashboard'],
        '/llm-analytics/generations': ['LLMAnalytics', 'llmAnalyticsGenerations'],
        '/llm-analytics/traces': ['LLMAnalytics', 'llmAnalyticsTraces'],
        '/llm-analytics/traces/:id': ['LLMAnalyticsTrace', 'llmAnalytics'],
        '/llm-analytics/users': ['LLMAnalytics', 'llmAnalyticsUsers'],
        '/llm-analytics/errors': ['LLMAnalytics', 'llmAnalyticsErrors'],
        '/llm-analytics/sessions': ['LLMAnalytics', 'llmAnalyticsSessions'],
        '/llm-analytics/sessions/:id': ['LLMAnalyticsSession', 'llmAnalytics'],
        '/llm-analytics/playground': ['LLMAnalytics', 'llmAnalyticsPlayground'],
        '/llm-analytics/datasets': ['LLMAnalyticsDatasets', 'llmAnalyticsDatasets'],
        '/llm-analytics/datasets/:id': ['LLMAnalyticsDataset', 'llmAnalyticsDataset'],
        '/llm-analytics/evaluations': ['LLMAnalyticsEvaluations', 'llmAnalyticsEvaluations'],
        '/llm-analytics/evaluations/templates': ['LLMAnalyticsEvaluationTemplates', 'llmAnalyticsEvaluationTemplates'],
        '/llm-analytics/evaluations/:id': ['LLMAnalyticsEvaluation', 'llmAnalyticsEvaluation'],
        '/llm-analytics/prompts': ['LLMAnalyticsPrompts', 'llmAnalyticsPrompts'],
        '/llm-analytics/prompts/:name': ['LLMAnalyticsPrompt', 'llmAnalyticsPrompt'],
        '/llm-analytics/settings': ['LLMAnalytics', 'llmAnalyticsSettings'],
        '/llm-analytics/clusters': ['LLMAnalyticsClusters', 'llmAnalyticsClusters'],
        '/llm-analytics/clusters/:runId': ['LLMAnalyticsClusters', 'llmAnalyticsClusters'],
        '/llm-analytics/clusters/:runId/:clusterId': ['LLMAnalyticsCluster', 'llmAnalyticsCluster'],
    },
    redirects: {
        '/llm-analytics': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/dashboard`, searchParams, hashParams).url,
        '/llm-observability': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/dashboard`, searchParams, hashParams).url,
        '/llm-observability/dashboard': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/dashboard`, searchParams, hashParams).url,
        '/llm-observability/generations': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/generations`, searchParams, hashParams).url,
        '/llm-observability/traces': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/traces`, searchParams, hashParams).url,
        '/llm-observability/traces/:id': (params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/traces/${params.id}`, searchParams, hashParams).url,
        '/llm-observability/users': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/users`, searchParams, hashParams).url,
        '/llm-observability/playground': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics/playground`, searchParams, hashParams).url,
    },
    urls: {
        llmAnalyticsDashboard: (): string => '/llm-analytics/dashboard',
        llmAnalyticsGenerations: (): string => '/llm-analytics/generations',
        llmAnalyticsTraces: (): string => '/llm-analytics/traces',
        llmAnalyticsTrace: (
            id: string,
            params?: {
                event?: string
                timestamp?: string
                exception_ts?: string
                search?: string
                tab?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/llm-analytics/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        llmAnalyticsUsers: (): string => '/llm-analytics/users',
        llmAnalyticsErrors: (): string => '/llm-analytics/errors',
        llmAnalyticsSessions: (): string => '/llm-analytics/sessions',
        llmAnalyticsSession: (
            id: string,
            params?: {
                timestamp?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/llm-analytics/sessions/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        llmAnalyticsPlayground: (): string => '/llm-analytics/playground',
        llmAnalyticsDatasets: (): string => '/llm-analytics/datasets',
        llmAnalyticsDataset: (id: string, params?: { item?: string }): string =>
            combineUrl(`/llm-analytics/datasets/${id}`, params).url,
        llmAnalyticsEvaluations: (): string => '/llm-analytics/evaluations',
        llmAnalyticsEvaluationTemplates: (): string => '/llm-analytics/evaluations/templates',
        llmAnalyticsEvaluation: (id: string): string => `/llm-analytics/evaluations/${id}`,
        llmAnalyticsPrompts: (): string => '/llm-analytics/prompts',
        llmAnalyticsPrompt: (name: string): string => `/llm-analytics/prompts/${name}`,
        llmAnalyticsSettings: (): string => '/llm-analytics/settings',
        llmAnalyticsClusters: (runId?: string): string =>
            runId ? `/llm-analytics/clusters/${encodeURIComponent(runId)}` : '/llm-analytics/clusters',
        llmAnalyticsCluster: (runId: string, clusterId: number): string =>
            `/llm-analytics/clusters/${encodeURIComponent(runId)}/${clusterId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'LLM analytics',
            intents: [
                ProductKey.LLM_ANALYTICS,
                ProductKey.LLM_EVALUATIONS,
                ProductKey.LLM_DATASETS,
                ProductKey.LLM_PROMPTS,
                ProductKey.LLM_CLUSTERS,
            ],
            category: 'AI Analytics',
            visualOrder: 1,
            type: 'llm_analytics',
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsDashboard(),
            sceneKey: 'LLMAnalytics',
        },
        {
            path: 'Clusters',
            intents: [ProductKey.LLM_CLUSTERS],
            category: 'AI Analytics',
            type: 'llm_clusters',
            iconType: 'llm_clusters' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-clusters-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsClusters(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_CLUSTERS_TAB,
            tags: ['alpha'],
            sceneKey: 'LLMAnalyticsClusters',
        },
        {
            path: 'Datasets',
            intents: [ProductKey.LLM_DATASETS],
            category: 'AI Analytics',
            type: 'llm_datasets',
            iconType: 'llm_datasets' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-datasets-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsDatasets(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_DATASETS,
            tags: ['beta'],
            sceneKey: 'LLMAnalyticsDatasets',
        },
        {
            path: 'Evaluations',
            intents: [ProductKey.LLM_EVALUATIONS],
            category: 'AI Analytics',
            type: 'llm_evaluations',
            iconType: 'llm_evaluations' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-evaluations-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsEvaluations(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS,
            tags: ['beta'],
            sceneKey: 'LLMAnalyticsEvaluations',
        },
        {
            path: 'Prompts',
            intents: [ProductKey.LLM_PROMPTS],
            category: 'AI Analytics',
            type: 'llm_prompts',
            iconType: 'llm_prompts' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-prompts-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsPrompts(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_PROMPTS,
            tags: ['alpha'],
            sceneKey: 'LLMAnalyticsPrompts',
        },
    ],
}
