import { toParams } from 'lib/utils/url'
import { urls } from 'scenes/urls'

import { ExperimentMetric, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

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
    scenes: {
        Experiments: {
            name: 'Experiments',
            import: () => import('./frontend/experiments/Experiments'),
            projectBased: true,
            activityScope: 'Experiment',
            description:
                'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or due to chance.',
            iconType: 'experiment',
        },
        Experiment: {
            name: 'Experiment',
            import: () => import('./frontend/experiments/Experiment'),
            projectBased: true,
            activityScope: 'Experiment',
            iconType: 'experiment',
        },
        ExperimentsSharedMetrics: {
            name: 'Shared metrics',
            import: () => import('./frontend/experiments/SharedMetrics/SharedMetrics'),
            projectBased: true,
            activityScope: 'Experiment',
        },
        ExperimentsSharedMetric: {
            name: '',
            import: () => import('./frontend/experiments/SharedMetrics/SharedMetric'),
            projectBased: true,
            activityScope: 'Experiment',
        },
    },
    routes: {
        '/experiments': ['Experiments', 'experiments'],
        '/experiments/shared-metrics': ['ExperimentsSharedMetrics', 'experimentsSharedMetrics'],
        '/experiments/shared-metrics/:id': ['ExperimentsSharedMetric', 'experimentsSharedMetric'],
        '/experiments/shared-metrics/:id/:action': ['ExperimentsSharedMetric', 'experimentsSharedMetric'],
        '/experiments/:id': ['Experiment', 'experiment'],
        '/experiments/:id/:formMode': ['Experiment', 'experiment'],
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
