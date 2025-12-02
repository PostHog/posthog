import api from 'lib/api'
import { toParams } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ExperimentMetric, ProductKey } from '~/queries/schema/schema-general'

import { Experiment, FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

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
            fetch: (ref: string) => api.experiments.get(parseInt(ref)),
            getName: (obj: Experiment) => obj.name || 'Untitled Experiment',
            states: (obj: Experiment) => [
                {
                    name: 'Started',
                    value: obj.start_date,
                },
            ],
            actions: (obj: Experiment) => [
                {
                    name: 'Archive experiment',
                    if: !obj.archived,
                    perform: () => api.experiments.update(parseInt(String(obj.id)), { archived: true }),
                },
            ],
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
            category: 'Features',
            type: 'experiment',
            href: urls.experiments(),
            iconType: 'experiment',
            iconColor: ['var(--color-product-experiments-light)'] as FileSystemIconColor,
            sceneKey: 'Experiments',
            sceneKeys: ['Experiments', 'Experiment'],
        },
    ],
}
