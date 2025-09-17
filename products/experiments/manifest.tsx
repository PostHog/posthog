import { toParams } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ExperimentMetric } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Experiments',
    urls: {
        experiment: (
            id: string | number,
            formMode?: string | null,
            options?: {
                metric?: ExperimentMetric
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
            iconType: 'experiment',
            href: (ref: string) => urls.experiment(ref),
            iconColor: ['var(--color-product-experiments-light)'],
            filterKey: 'experiment',
        },
    },
    treeItemsNew: [
        {
            path: `Experiment`,
            type: 'experiment',
            href: urls.experiment('new'),
            iconType: 'experiment',
            iconColor: ['var(--color-product-experiments-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [
        {
            path: `Experiments`,
            category: 'Features',
            type: 'experiment',
            href: urls.experiments(),
            iconType: 'experiment',
            iconColor: ['var(--color-product-experiments-light)'] as FileSystemIconColor,
        },
    ],
}
