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
                const featuresWithCounts = await Promise.all(
                    response.results.map(async (feature) => {
                        const key = `$feature_enrollment/${feature.feature_flag.key}`
                        const optInCount = await api.persons.list({
                            properties: [
                                {
                                    key: key,
                                    value: ['true'],
                                    operator: 'exact',
                                    type: 'person',
                                },
                            ],
                        })
                        return {
                            ...feature,
                            opt_in_count: optInCount.count,
                        }
                    })
                )
                return featuresWithCounts
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
    }),
    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
    }),
])
