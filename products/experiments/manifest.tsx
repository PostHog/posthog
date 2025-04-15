import { IconTestTube } from '@posthog/icons'
import { toParams } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Experiments',
    urls: {
        experiment: (
            id: string | number,
            options?: {
                metric?: ExperimentTrendsQuery | ExperimentFunnelsQuery
                name?: string
            }
        ): string => `/experiments/${id}${options ? `?${toParams(options)}` : ''}`,
        experiments: (): string => '/experiments',
        experimentsSharedMetrics: (): string => '/experiments/shared-metrics',
        experimentsSharedMetric: (id: string | number): string => `/experiments/shared-metrics/${id}`,
    },
    fileSystemTypes: {
        experiment: {
            icon: <IconTestTube />,
            href: (ref: string) => urls.experiment(ref),
        },
    },
    treeItemsNew: [
        {
            path: `Experiment`,
            type: 'experiment',
            href: () => urls.experiment('new'),
        },
    ],
}
