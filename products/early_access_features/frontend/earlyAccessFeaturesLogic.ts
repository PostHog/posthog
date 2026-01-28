import FuseClass from 'fuse.js'
import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, EarlyAccessFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'

export const earlyAccessFeaturesFuse = new FuseClass<EarlyAccessFeatureType>([], {
    keys: ['name', 'description', 'stage'],
    threshold: 0.3,
})

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
                if (!searchTerm.trim()) {
                    return earlyAccessFeatures
                }

                const results = earlyAccessFeaturesFuse.search(searchTerm)
                return results.map((result) => result.item)
            },
        ],
    }),

    subscriptions({
        earlyAccessFeatures: (earlyAccessFeatures: EarlyAccessFeatureType[]) => {
            earlyAccessFeaturesFuse.setCollection(earlyAccessFeatures || [])
        },
    }),

    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
    }),
])
