import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { earlyAccessFeatures } from './urls'

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
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.EarlyAccessFeatures,
                    name: 'Early access features',
                    path: earlyAccessFeatures(),
                },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
    }),
])
