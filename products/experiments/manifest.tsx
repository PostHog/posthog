import { IconTestTube } from '@posthog/icons'
import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { toParams } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Experiments',
    urls: {
        experiment: (
            id: string | number,
            formMode?: string | null,
            options?: {
                metric?: ExperimentTrendsQuery | ExperimentFunnelsQuery
                name?: string
            }
        ): string => {
            const baseUrl = formMode ? `/experiments/${id}/${formMode}` : `/experiments/${id}`
            return `${baseUrl}${options ? `?${toParams(options)}` : ''}`
        },
        experiments: (): string => '/experiments',
        experimentsSharedMetrics: (): string => '/experiments/shared-metrics',
        experimentsSharedMetric: (id: string | number, action?: string): string =>
            action ? `/experiments/shared-metrics/${id}/${action}` : `/experiments/shared-metrics/${id}`,
    },
    fileSystemTypes: {
        experiment: {
            name: 'Experiment',
            icon: <IconTestTube />,
            href: (ref: string) => urls.experiment(ref),
            iconColor: ['var(--product-experiments-light)'],
            filterKey: 'experiment',
        },
    },
    treeItemsNew: [
        {
            path: `Experiment`,
            type: 'experiment',
            href: urls.experiment('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: `Experiments`,
            type: 'experiment',
            href: urls.experiments(),
            visualOrder: PRODUCT_VISUAL_ORDER.experiments,
        },
    ],
}
