import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'LLM Observability',
    scenes: {
        LLMObservability: {
            import: () => import('./frontend/LLMObservabilityScene'),
            projectBased: true,
            name: 'LLM observability',
            activityScope: 'LLMObservability',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
        LLMObservabilityTrace: {
            import: () => import('./frontend/LLMObservabilityTraceScene'),
            projectBased: true,
            name: 'LLM observability trace',
            activityScope: 'LLMObservability',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
        LLMObservabilityUsers: {
            import: () => import('./frontend/LLMObservabilityUsers'),
            projectBased: true,
            name: 'LLM observability users',
            activityScope: 'LLMObservability',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
        LLMObservabilityPlayground: {
            import: () => import('./frontend/LLMObservabilityPlaygroundScene'),
            projectBased: true,
            name: 'LLM playground',
            activityScope: 'LLMObservability',
            layout: 'app-container',
            defaultDocsPath: '/docs/ai-engineering/observability',
        },
    },
    routes: {
        '/llm-observability': ['LLMObservability', 'llmObservability'],
        '/llm-observability/dashboard': ['LLMObservability', 'llmObservabilityDashboard'],
        '/llm-observability/generations': ['LLMObservability', 'llmObservabilityGenerations'],
        '/llm-observability/traces': ['LLMObservability', 'llmObservabilityTraces'],
        '/llm-observability/traces/:id': ['LLMObservabilityTrace', 'llmObservability'],
        '/llm-observability/users': ['LLMObservability', 'llmObservabilityUsers'],
        '/llm-observability/playground': ['LLMObservability', 'llmObservabilityPlayground'],
    },
    redirects: {},
    urls: {
        llmObservabilityDashboard: (): string => '/llm-observability',
        llmObservabilityGenerations: (): string => '/llm-observability/generations',
        llmObservabilityTraces: (): string => '/llm-observability/traces',
        llmObservabilityTrace: (
            id: string,
            params?: {
                event?: string
                timestamp?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/llm-observability/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        llmObservabilityUsers: (): string => '/llm-observability/users',
        llmObservabilityPlayground: (): string => '/llm-observability/playground',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'LLM observability',
            iconType: 'ai',
            href: urls.llmObservabilityDashboard(),
            flag: FEATURE_FLAGS.LLM_OBSERVABILITY,
        },
    ],
}
