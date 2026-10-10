/**
 * Product manifest for warehouse_sources.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'ELT',
    scenes: {
        PipelineOverview: {
            import: () => import('./frontend/scenes/PipelineOverviewScene/PipelineOverviewScene'),
            projectBased: true,
            name: 'ELT',
            description: 'Every source you import from and every destination you write to, with the health of each.',
            iconType: 'data_pipeline',
            docsHref: 'https://posthog.com/docs/data-warehouse',
        },
    },
    routes: {
        '/etl': ['PipelineOverview', 'pipelineOverview'],
    },
    redirects: {},
    urls: {
        etlOverview: (): string => '/etl',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            // Keep the persisted product identifier stable while showing the corrected label.
            path: 'ETL',
            displayLabel: 'ELT',
            // Reuses the warehouse product key rather than minting a new one: this is a surface
            // over the same sources and destinations, so setup state and Quick Start tracking
            // should read as the same product.
            intents: [ProductKey.DATA_WAREHOUSE],
            category: ProductItemCategory.TOOLS,
            iconType: 'data_pipeline',
            iconColor: ['var(--color-product-data-warehouse-light)'],
            href: urls.etlOverview(),
            searchKeywords: ['syncs', 'sync health'],
            // The nav entry and the scene body are gated separately. This hides the entry; the
            // scene itself still has to refuse a direct visit.
            flag: FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION,
            sceneKey: 'PipelineOverview',
            sceneKeys: ['PipelineOverview'],
        },
    ],
}
