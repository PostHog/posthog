import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, EarlyAccessFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'

export const earlyAccessFeaturesLogic = kea<earlyAccessFeaturesLogicType>([
    path(['products', 'earlyAccessFeatures', 'frontend', 'earlyAccessFeaturesLogic']),
    loaders({
        earlyAccessFeatures: {
            __default: [] as EarlyAccessFeatureType[],
            loadEarlyAccessFeatures: async () => {
                const response = await api.earlyAccessFeatures.list()
                return response.results
            },
        },
        featureEnrollmentCounts: {
            __default: {} as Record<string, number>,
            loadFeatureEnrollmentCounts: async () => {
                const response = await api.get('api/projects/@current/early_access_feature/enrollment_counts/')
                return response
            },
        },
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'EarlyAccessFeatures',
                    name: 'Early access features',
                    path: urls.earlyAccessFeatures(),
                },
            ],
        ],
        featuresWithCounts: [
            (s) => [s.earlyAccessFeatures, s.featureEnrollmentCounts],
            (features, counts): EarlyAccessFeatureType[] =>
                features.map((feature) => ({
                    ...feature,
                    opt_in_count: counts[`$feature_enrollment/${feature.feature_flag.key}`] || 0,
                })),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
        actions.loadFeatureEnrollmentCounts()
    }),
])
