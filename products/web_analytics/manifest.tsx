import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Web Analytics',
    urls: {
        webAnalytics: (): string => `/web`,
        webAnalyticsWebVitals: (): string => `/web/web-vitals`,
        webAnalyticsPageReports: (): string => `/web/page-reports`,
        webAnalyticsMarketing: (): string => `/web/marketing`,
        webAnalyticsHealth: (): string => `/web/health`,
        webAnalyticsLive: (): string => `/web/live`,
        webAnalyticsBotAnalytics: (): string => `/web/bot-analytics`,
        heatmaps: (params?: string): string =>
            `/heatmaps${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
        heatmapNew: (params?: string): string =>
            `/heatmaps/new${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
        heatmapRecording: (params?: string): string =>
            `/heatmaps/recording${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
        heatmap: (id: string | number): string => `/heatmaps/${id}`,
    },
    scenes: {
        Heatmaps: {
            name: 'Heatmaps',
            import: () => import('./frontend/heatmaps/scenes/heatmaps/HeatmapsScene'),
            projectBased: true,
            iconType: 'heatmap',
            description: 'Heatmaps are a way to visualize user behavior on your website.',
        },
        Heatmap: {
            name: 'Heatmap',
            import: () => import('./frontend/heatmaps/scenes/heatmap/HeatmapScene'),
            projectBased: true,
            iconType: 'heatmap',
        },
        HeatmapNew: {
            name: 'New heatmap',
            import: () => import('./frontend/heatmaps/scenes/heatmap/HeatmapNewScene'),
            projectBased: true,
            iconType: 'heatmap',
        },
        HeatmapRecording: {
            name: 'Heatmap recording',
            import: () => import('./frontend/heatmaps/scenes/heatmap/HeatmapRecordingScene'),
            projectBased: true,
            iconType: 'heatmap',
        },
    },
    routes: {
        '/heatmaps': ['Heatmaps', 'heatmaps'],
        '/heatmaps/new': ['HeatmapNew', 'heatmapNew'],
        '/heatmaps/recording': ['HeatmapRecording', 'heatmapRecording'],
        '/heatmaps/:id': ['Heatmap', 'heatmap'],
    },
    fileSystemTypes: {},
    treeItemsProducts: [
        {
            path: 'Web analytics',
            intents: [ProductKey.WEB_ANALYTICS],
            category: ProductItemCategory.ANALYTICS,
            iconType: 'web_analytics',
            iconColor: ['var(--color-product-web-analytics-light)'] as FileSystemIconColor,
            href: urls.webAnalytics(),
            sceneKey: 'WebAnalytics',
            sceneKeys: ['WebAnalytics'],
        },
    ],
    treeItemsMetadata: [],
}
