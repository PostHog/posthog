import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import { LLM_ANALYTICS_CLUSTER_URL_PATTERN } from './frontend/clusters/constants'

export const manifest: ProductManifest = {
    name: 'AI observability',
    scenes: {
        LLMAnalytics: {
            import: () => import('./frontend/LLMAnalyticsScene'),
            projectBased: true,
            name: 'AI observability',
            layout: 'app-container',
            description: 'Analyze and understand your AI usage and performance.',
            iconType: 'llm_analytics',
        },
        LLMAnalyticsTrace: {
            import: () => import('./frontend/LLMAnalyticsTraceScene'),
            projectBased: true,
            name: 'AI observability trace',
            layout: 'app-container',
        },
        LLMAnalyticsSession: {
            import: () => import('./frontend/LLMAnalyticsSessionScene'),
            projectBased: true,
            name: 'AI observability session',
            layout: 'app-container',
        },
        LLMAnalyticsUsers: {
            import: () => import('./frontend/LLMAnalyticsUsers'),
            projectBased: true,
            name: 'AI observability users',
            layout: 'app-container',
        },
        LLMAnalyticsPlayground: {
            import: () => import('./frontend/playground/LLMAnalyticsPlaygroundScene'),
            projectBased: true,
            name: 'Playground',
            description: 'Test and experiment with LLM prompts in a sandbox environment.',
            layout: 'app-full-scene-height',
            iconType: 'llm_playground',
        },
        LLMAnalyticsDatasets: {
            import: () => import('./frontend/datasets/LLMAnalyticsDatasetsScene'),
            projectBased: true,
            name: 'Datasets',
            description: 'Manage datasets for testing and evaluation.',
            layout: 'app-container',
            iconType: 'llm_datasets',
        },
        LLMAnalyticsDataset: {
            import: () => import('./frontend/datasets/LLMAnalyticsDatasetScene'),
            projectBased: true,
            name: 'Dataset',
            layout: 'app-container',
            iconType: 'llm_datasets',
        },
        LLMAnalyticsEvaluations: {
            import: () => import('./frontend/evaluations/LLMAnalyticsEvaluationsScene'),
            projectBased: true,
            name: 'Evaluations',
            description: 'Configure and monitor automated LLM output evaluations.',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            iconType: 'llm_evaluations',
        },
        LLMAnalyticsEvaluation: {
            import: () => import('./frontend/evaluations/LLMAnalyticsEvaluation'),
            projectBased: true,
            name: 'Evaluation',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            iconType: 'llm_evaluations',
        },
        LLMAnalyticsEvaluationTemplates: {
            import: () => import('./frontend/evaluations/EvaluationTemplates'),
            projectBased: true,
            name: 'Evaluation templates',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            iconType: 'llm_evaluations',
        },
        LLMAnalyticsTags: {
            import: () => import('./frontend/tags/LLMAnalyticsTagsScene'),
            projectBased: true,
            name: 'Taggers',
            description: 'Add custom tags to your AI generations automatically.',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            iconType: 'llm_tags',
        },
        LLMAnalyticsTag: {
            import: () => import('./frontend/tags/LLMAnalyticsTag'),
            projectBased: true,
            name: 'Tagger',
            activityScope: 'LLMAnalytics',
            layout: 'app-container',
            iconType: 'llm_tags',
        },
        LLMAnalyticsPrompts: {
            import: () => import('./frontend/prompts/LLMPromptsScene'),
            projectBased: true,
            name: 'Prompts',
            description: 'Track and manage your LLM prompts.',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        LLMAnalyticsPrompt: {
            import: () => import('./frontend/prompts/LLMPromptScene'),
            projectBased: true,
            name: 'Prompt',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        LLMAnalyticsSkills: {
            import: () => import('./frontend/skills/LLMSkillsScene'),
            projectBased: true,
            name: 'Skills',
            description: 'Manage versioned agent skills that any MCP-connected agent can discover and use.',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        LLMAnalyticsSkill: {
            import: () => import('./frontend/skills/LLMSkillScene'),
            projectBased: true,
            name: 'Skill',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
        LLMAnalyticsClusters: {
            import: () => import('./frontend/clusters/LLMAnalyticsClustersScene'),
            projectBased: true,
            name: 'Clusters',
            description: 'Discover patterns and clusters in your AI usage.',
            layout: 'app-container',
            iconType: 'llm_clusters',
        },
        LLMAnalyticsCluster: {
            import: () => import('./frontend/clusters/LLMAnalyticsClusterScene'),
            projectBased: true,
            name: 'AI observability cluster',
            layout: 'app-container',
            iconType: 'llm_clusters',
        },
    },
    routes: {
        '/ai-observability/dashboard': ['LLMAnalytics', 'llmAnalyticsDashboard'],
        '/ai-observability/generations': ['LLMAnalytics', 'llmAnalyticsGenerations'],
        '/ai-observability/reviews': ['LLMAnalytics', 'llmAnalyticsReviews'],
        '/ai-observability/traces': ['LLMAnalytics', 'llmAnalyticsTraces'],
        '/ai-observability/traces/:id': ['LLMAnalyticsTrace', 'llmAnalytics'],
        '/ai-observability/users': ['LLMAnalytics', 'llmAnalyticsUsers'],
        '/ai-observability/errors': ['LLMAnalytics', 'llmAnalyticsErrors'],
        '/ai-observability/tools': ['LLMAnalytics', 'llmAnalyticsTools'],
        '/ai-observability/sentiment': ['LLMAnalytics', 'llmAnalyticsSentiment'],
        '/ai-observability/sessions': ['LLMAnalytics', 'llmAnalyticsSessions'],
        '/ai-observability/sessions/:id': ['LLMAnalyticsSession', 'llmAnalytics'],
        '/ai-observability/playground': ['LLMAnalyticsPlayground', 'llmAnalyticsPlayground'],
        '/ai-observability/clusters': ['LLMAnalyticsClusters', 'llmAnalyticsClusters'],
        '/ai-observability/clusters/:runId': ['LLMAnalyticsClusters', 'llmAnalyticsClusters'],
        [LLM_ANALYTICS_CLUSTER_URL_PATTERN]: ['LLMAnalyticsCluster', 'llmAnalyticsCluster'],
        '/ai-evals/datasets': ['LLMAnalyticsDatasets', 'llmAnalyticsDatasets'],
        '/ai-evals/datasets/:id': ['LLMAnalyticsDataset', 'llmAnalyticsDataset'],
        '/ai-evals/taggers': ['LLMAnalyticsTags', 'llmAnalyticsTags'],
        '/ai-evals/taggers/:id': ['LLMAnalyticsTag', 'llmAnalyticsTag'],
        '/ai-evals/evaluations': ['LLMAnalyticsEvaluations', 'llmAnalyticsEvaluations'],
        '/ai-evals/evaluations/offline/experiments': ['LLMAnalyticsEvaluations', 'llmAnalyticsOfflineEvaluations'],
        '/ai-evals/evaluations/offline/experiments/:experimentId': [
            'LLMAnalyticsEvaluations',
            'llmAnalyticsOfflineEvaluationExperiment',
        ],
        '/ai-evals/evaluations/templates': ['LLMAnalyticsEvaluationTemplates', 'llmAnalyticsEvaluationTemplates'],
        '/ai-evals/evaluations/:id': ['LLMAnalyticsEvaluation', 'llmAnalyticsEvaluation'],
        '/prompt-management/prompts': ['LLMAnalyticsPrompts', 'llmAnalyticsPrompts'],
        '/prompt-management/prompts/:name': ['LLMAnalyticsPrompt', 'llmAnalyticsPrompt'],
        '/prompt-management/skills': ['LLMAnalyticsSkills', 'llmAnalyticsSkills'],
        '/prompt-management/skills/:name': ['LLMAnalyticsSkill', 'llmAnalyticsSkill'],
    },
    redirects: {
        '/ai-observability': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDashboard(), searchParams, hashParams).url,
        '/ai-observability/settings': (_params, searchParams) =>
            combineUrl(urls.settings('environment-llm-analytics', 'llm-analytics-byok'), searchParams).url,
        '/ai-evals': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsEvaluations(), searchParams, hashParams).url,
        '/ai-evals/evaluations/offline': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsOfflineEvaluations(), searchParams, hashParams).url,
        '/ai-evals/tags': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTags(), searchParams, hashParams).url,
        '/ai-evals/tags/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTag(params.id), searchParams, hashParams).url,
        '/prompt-management': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsPrompts(), searchParams, hashParams).url,
        '/llm-analytics': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDashboard(), searchParams, hashParams).url,
        '/llm-analytics/settings': (_params, searchParams) =>
            combineUrl(urls.settings('environment-llm-analytics', 'llm-analytics-byok'), searchParams).url,
        '/llm-analytics/dashboard': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDashboard(), searchParams, hashParams).url,
        '/llm-analytics/generations': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsGenerations(), searchParams, hashParams).url,
        '/llm-analytics/reviews': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsReviews(), searchParams, hashParams).url,
        '/llm-analytics/traces': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTraces(), searchParams, hashParams).url,
        '/llm-analytics/traces/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTrace(params.id), searchParams, hashParams).url,
        '/llm-analytics/users': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsUsers(), searchParams, hashParams).url,
        '/llm-analytics/errors': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsErrors(), searchParams, hashParams).url,
        '/llm-analytics/tools': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTools(), searchParams, hashParams).url,
        '/llm-analytics/sentiment': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsSentiment(), searchParams, hashParams).url,
        '/llm-analytics/sessions': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsSessions(), searchParams, hashParams).url,
        '/llm-analytics/sessions/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsSession(params.id), searchParams, hashParams).url,
        '/llm-analytics/playground': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsPlayground(), searchParams, hashParams).url,
        '/llm-analytics/clusters': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsClusters(), searchParams, hashParams).url,
        '/llm-analytics/clusters/:runId': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsClusters(params.runId), searchParams, hashParams).url,
        '/llm-analytics/clusters/:runId/:clusterId': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsCluster(params.runId, params.clusterId), searchParams, hashParams).url,
        '/llm-analytics/datasets': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDatasets(), searchParams, hashParams).url,
        '/llm-analytics/datasets/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDataset(params.id), searchParams, hashParams).url,
        '/llm-analytics/tags': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTags(), searchParams, hashParams).url,
        '/llm-analytics/tags/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTag(params.id), searchParams, hashParams).url,
        '/llm-analytics/evaluations': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsEvaluations(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/offline': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsOfflineEvaluations(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/offline/experiments': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsOfflineEvaluations(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/offline/experiments/:experimentId': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsOfflineEvaluationExperiment(params.experimentId), searchParams, hashParams).url,
        '/llm-analytics/evaluations/templates': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsEvaluationTemplates(), searchParams, hashParams).url,
        '/llm-analytics/evaluations/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsEvaluation(params.id), searchParams, hashParams).url,
        '/llm-analytics/prompts': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsPrompts(), searchParams, hashParams).url,
        '/llm-analytics/prompts/:name': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsPrompt(params.name), searchParams, hashParams).url,
        '/llm-analytics/skills': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsSkills(), searchParams, hashParams).url,
        '/llm-analytics/skills/:name': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsSkill(params.name), searchParams, hashParams).url,
        '/llm-observability': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDashboard(), searchParams, hashParams).url,
        '/llm-observability/dashboard': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsDashboard(), searchParams, hashParams).url,
        '/llm-observability/generations': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsGenerations(), searchParams, hashParams).url,
        '/llm-observability/reviews': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsReviews(), searchParams, hashParams).url,
        '/llm-observability/traces': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTraces(), searchParams, hashParams).url,
        '/llm-observability/traces/:id': (params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsTrace(params.id), searchParams, hashParams).url,
        '/llm-observability/users': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsUsers(), searchParams, hashParams).url,
        '/llm-observability/playground': (_params, searchParams, hashParams) =>
            combineUrl(urls.llmAnalyticsPlayground(), searchParams, hashParams).url,
    },
    urls: {
        llmAnalyticsDashboard: (): string => '/ai-observability/dashboard',
        llmAnalyticsGenerations: (): string => '/ai-observability/generations',
        llmAnalyticsReviews: (): string => '/ai-observability/reviews',
        llmAnalyticsTraces: (): string => '/ai-observability/traces',
        llmAnalyticsTrace: (
            id: string,
            params?: {
                event?: string
                timestamp?: string
                exception_ts?: string
                search?: string
                tab?: string
                msg?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/ai-observability/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        llmAnalyticsUsers: (): string => '/ai-observability/users',
        llmAnalyticsErrors: (): string => '/ai-observability/errors',
        llmAnalyticsTools: (): string => '/ai-observability/tools',
        llmAnalyticsSentiment: (): string => '/ai-observability/sentiment',
        llmAnalyticsSessions: (): string => '/ai-observability/sessions',
        llmAnalyticsSession: (
            id: string,
            params?: {
                timestamp?: string
            }
        ): string => {
            const queryParams = new URLSearchParams(params)
            const stringifiedParams = queryParams.toString()
            return `/ai-observability/sessions/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        llmAnalyticsPlayground: (): string => '/ai-observability/playground',
        llmAnalyticsDatasets: (): string => '/ai-evals/datasets',
        llmAnalyticsDataset: (id: string, params?: { item?: string }): string =>
            combineUrl(`/ai-evals/datasets/${id}`, params).url,
        llmAnalyticsTags: (): string => '/ai-evals/taggers',
        llmAnalyticsTag: (id: string): string => `/ai-evals/taggers/${id}`,
        llmAnalyticsEvaluations: (): string => '/ai-evals/evaluations',
        llmAnalyticsOfflineEvaluations: (): string => '/ai-evals/evaluations/offline/experiments',
        llmAnalyticsOfflineEvaluationExperiment: (experimentId: string, encode: boolean = true): string =>
            `/ai-evals/evaluations/offline/experiments/${encode ? encodeURIComponent(experimentId) : experimentId}`,
        llmAnalyticsEvaluationTemplates: (): string => '/ai-evals/evaluations/templates',
        llmAnalyticsEvaluation: (id: string): string => `/ai-evals/evaluations/${id}`,
        llmAnalyticsPrompts: (): string => '/prompt-management/prompts',
        llmAnalyticsPrompt: (name: string): string => `/prompt-management/prompts/${name}`,
        llmAnalyticsSkills: (): string => '/prompt-management/skills',
        llmAnalyticsSkill: (name: string, params?: { file?: string; version?: number }): string =>
            combineUrl(`/prompt-management/skills/${name}`, params).url,
        llmAnalyticsClusters: (runId?: string): string =>
            runId ? `/ai-observability/clusters/${encodeURIComponent(runId)}` : '/ai-observability/clusters',
        llmAnalyticsCluster: (runId: string, clusterId: number | string): string =>
            `/ai-observability/clusters/${encodeURIComponent(runId)}/${clusterId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'LLM analytics',
            displayLabel: 'AI observability',
            intents: [
                ProductKey.LLM_ANALYTICS,
                ProductKey.LLM_EVALUATIONS,
                ProductKey.LLM_DATASETS,
                ProductKey.LLM_PROMPTS,
                ProductKey.LLM_CLUSTERS,
            ],
            category: ProductItemCategory.AI_ENGINEERING,
            visualOrder: 1,
            type: 'llm_analytics',
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsDashboard(),
            sceneKey: 'LLMAnalytics',
        },
        {
            path: 'Playground',
            intents: [ProductKey.LLM_ANALYTICS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_playground',
            iconType: 'llm_playground' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsPlayground(),
            sceneKey: 'LLMAnalyticsPlayground',
        },
        {
            path: 'Clusters',
            intents: [ProductKey.LLM_CLUSTERS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_clusters',
            iconType: 'llm_clusters' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-clusters-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsClusters(),
            sceneKey: 'LLMAnalyticsClusters',
        },
        {
            path: 'Datasets',
            intents: [ProductKey.LLM_DATASETS],
            category: ProductItemCategory.AI_ENGINEERING,
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
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_evaluations',
            iconType: 'llm_evaluations' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-evaluations-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsEvaluations(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS,
            sceneKey: 'LLMAnalyticsEvaluations',
        },
        {
            path: 'Taggers',
            intents: [ProductKey.LLM_ANALYTICS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_tags',
            iconType: 'llm_tags' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsTags(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_TAGS,
            tags: ['alpha'],
            sceneKey: 'LLMAnalyticsTags',
        },
        {
            path: 'Prompts',
            intents: [ProductKey.LLM_PROMPTS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_prompts',
            iconType: 'llm_prompts' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-prompts-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsPrompts(),
            flag: FEATURE_FLAGS.PROMPT_MANAGEMENT,
            tags: ['beta'],
            sceneKey: 'LLMAnalyticsPrompts',
        },
        {
            path: 'Skills',
            intents: [ProductKey.LLM_PROMPTS],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'llm_skills',
            iconType: 'llm_prompts' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-prompts-light)'] as FileSystemIconColor,
            href: urls.llmAnalyticsSkills(),
            flag: FEATURE_FLAGS.LLM_ANALYTICS_SKILLS,
            tags: ['beta'],
            sceneKey: 'LLMAnalyticsSkills',
        },
    ],
}
