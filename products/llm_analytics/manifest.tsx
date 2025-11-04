import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

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
        LLMAnalyticsErrors: {
            import: () => import('./frontend/LLMAnalyticsErrors'),
            projectBased: true,
            name: 'LLM analytics errors',
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
            import: () => import('./frontend/LLMAnalyticsScene'),
            projectBased: true,
            name: 'LLM analytics evaluations',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
        LLMAnalyticsEvaluation: {
            import: () => import('./frontend/evaluations/LLMAnalyticsEvaluation'),
            projectBased: true,
            name: 'LLM analytics evaluation',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/llm-analytics/installation',
        },
    },
    routes: {
        '/llm-analytics': ['LLMAnalytics', 'llmAnalytics'],
        '/llm-analytics/dashboard': ['LLMAnalytics', 'llmAnalyticsDashboard'],
        '/llm-analytics/generations': ['LLMAnalytics', 'llmAnalyticsGenerations'],
        '/llm-analytics/traces': ['LLMAnalytics', 'llmAnalyticsTraces'],
        '/llm-analytics/traces/:id': ['LLMAnalyticsTrace', 'llmAnalytics'],
        '/llm-analytics/users': ['LLMAnalytics', 'llmAnalyticsUsers'],
        '/llm-analytics/errors': ['LLMAnalytics', 'llmAnalyticsErrors'],
        '/llm-analytics/sessions': ['LLMAnalytics', 'llmAnalyticsSessions'],
        '/llm-analytics/sessions/:id': ['LLMAnalyticsSession', 'llmAnalytics'],
        '/llm-analytics/playground': ['LLMAnalytics', 'llmAnalyticsPlayground'],
        '/llm-analytics/datasets': ['LLMAnalytics', 'llmAnalyticsDatasets'],
        '/llm-analytics/datasets/:id': ['LLMAnalyticsDataset', 'llmAnalyticsDataset'],
        '/llm-analytics/evaluations': ['LLMAnalytics', 'llmAnalyticsEvaluations'],
        '/llm-analytics/evaluations/:id': ['LLMAnalyticsEvaluation', 'llmAnalyticsEvaluation'],
    },
    redirects: {
        '/llm-observability': (_params, searchParams, hashParams) =>
            combineUrl(`/llm-analytics`, searchParams, hashParams).url,
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
        llmAnalyticsDashboard: (): string => '/llm-analytics',
        llmAnalyticsGenerations: (): string => '/llm-analytics/generations',
        llmAnalyticsTraces: (): string => '/llm-analytics/traces',
        llmAnalyticsTrace: (
            id: string,
            params?: {
                event?: string
                timestamp?: string
                exception_ts?: string
                search?: string
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
        llmAnalyticsEvaluation: (id: string): string => `/llm-analytics/evaluations/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'LLM analytics',
            category: 'Analytics',
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsDashboard(),
            sceneKey: 'LLMAnalytics',
        },
    ],
}
