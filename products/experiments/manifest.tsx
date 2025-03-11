import { toParams } from 'lib/utils'

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
}
