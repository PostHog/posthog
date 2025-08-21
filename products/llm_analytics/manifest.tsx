import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'LLM Analytics',
    scenes: {
        LLMAnalytics: {
            import: () => import('./frontend/LLMAnalyticsScene'),
            projectBased: true,
            name: 'LLM analytics',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
        LLMAnalyticsTrace: {
            import: () => import('./frontend/LLMAnalyticsTraceScene'),
            projectBased: true,
            name: 'LLM analytics trace',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
        LLMAnalyticsUsers: {
            import: () => import('./frontend/LLMAnalyticsUsers'),
            projectBased: true,
            name: 'LLM analytics users',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
        LLMAnalyticsPlayground: {
            import: () => import('./frontend/LLMAnalyticsPlaygroundScene'),
            projectBased: true,
            name: 'LLM playground',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
    },
    routes: {
        '/llm-analytics': ['LLMAnalytics', 'llmAnalytics'],
        '/llm-analytics/dashboard': ['LLMAnalytics', 'llmAnalyticsDashboard'],
        '/llm-analytics/generations': ['LLMAnalytics', 'llmAnalyticsGenerations'],
        '/llm-analytics/traces': ['LLMAnalytics', 'llmAnalyticsTraces'],
        '/llm-analytics/traces/:id': ['LLMAnalyticsTrace', 'llmAnalytics'],
        '/llm-analytics/users': ['LLMAnalytics', 'llmAnalyticsUsers'],
        '/llm-analytics/playground': ['LLMAnalytics', 'llmAnalyticsPlayground'],
    },
    redirects: {
        '/llm-observability': '/llm-analytics',
        '/llm-observability/dashboard': '/llm-analytics/dashboard',
        '/llm-observability/generations': '/llm-analytics/generations',
        '/llm-observability/traces': '/llm-analytics/traces',
        '/llm-observability/traces/:id': '/llm-analytics/traces/:id',
        '/llm-observability/users': '/llm-analytics/users',
        '/llm-observability/playground': '/llm-analytics/playground',
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
                search?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/llm-analytics/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        llmAnalyticsUsers: (): string => '/llm-analytics/users',
        llmAnalyticsPlayground: (): string => '/llm-analytics/playground',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'LLM analytics',
            category: 'Analytics',
            iconType: 'ai',
            href: urls.llmAnalyticsDashboard(),
            flag: FEATURE_FLAGS.LLM_OBSERVABILITY,
            tags: ['beta'],
        },
    ],
}
