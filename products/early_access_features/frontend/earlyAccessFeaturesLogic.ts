import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { createFeaturePreviewSearch } from 'lib/utils/fuseSearch'
import { urls } from 'scenes/urls'

import { Breadcrumb, EarlyAccessFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'

const search = createFeaturePreviewSearch<EarlyAccessFeatureType>()

export const earlyAccessFeaturesLogic = kea<earlyAccessFeaturesLogicType>([
    path(['products', 'earlyAccessFeatures', 'frontend', 'earlyAccessFeaturesLogic']),

    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),

    loaders({
        earlyAccessFeatures: {
            __default: [] as EarlyAccessFeatureType[],
            loadEarlyAccessFeatures: async () => {
                const response = await api.earlyAccessFeatures.list()
                return response.results
            },
        },
    }),

    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'EarlyAccessFeatures',
                    name: 'Early access features',
                    path: urls.earlyAccessFeatures(),
                    iconType: 'early_access_feature',
                },
            ],
        ],

        filteredEarlyAccessFeatures: [
            (s) => [s.earlyAccessFeatures, s.searchTerm],
            (earlyAccessFeatures: EarlyAccessFeatureType[], searchTerm: string): EarlyAccessFeatureType[] => {
                return search(earlyAccessFeatures, searchTerm)
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
    }),
])
