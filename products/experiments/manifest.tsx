import { toParams } from 'lib/utils/url'
import { urls } from 'scenes/urls'

import { ExperimentMetric, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Experiments',
    scenes: {
        Experiments: {
            import: () => import('./frontend/scenes/ExperimentsScene'),
            projectBased: true,
            name: 'Experiments',
            activityScope: ActivityScope.EXPERIMENT,
            description:
                'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or due to chance.',
            iconType: 'experiment',
        },
    },
    routes: { '/experiments': ['Experiments', 'experiments'] },
    urls: {
        experiment: (
            id: string | number,
            formMode?: string | null,
            options?: {
                metric?: ExperimentMetric
                name?: string
                tab?: string
            }
        ): string => {
            const baseUrl = formMode ? `/experiments/${id}/${formMode}` : `/experiments/${id}`
            const params = options ? toParams(options) : ''
            return params ? `${baseUrl}?${params}` : baseUrl
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
            sceneKeys: ['Experiments', 'Experiment'],
        },
    ],
    treeItemsProducts: [
        {
            path: `Experiments`,
            intents: [ProductKey.EXPERIMENTS],
            category: ProductItemCategory.FEATURES,
            type: 'experiment',
            href: urls.experiments(),
            iconType: 'experiment',
            iconColor: ['var(--color-product-experiments-light)'] as FileSystemIconColor,
            sceneKey: 'Experiments',
            sceneKeys: ['Experiments', 'Experiment'],
        },
    ],
}
