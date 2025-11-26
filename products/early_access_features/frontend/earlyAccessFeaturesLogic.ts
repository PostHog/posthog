import FuseClass from 'fuse.js'
import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb, EarlyAccessFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'

export interface EarlyAccessFeaturesFuse extends FuseClass<EarlyAccessFeatureType> {}

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

        featuresFuse: [
            (s) => [s.earlyAccessFeatures],
            (earlyAccessFeatures: EarlyAccessFeatureType[]): EarlyAccessFeaturesFuse => {
                return new FuseClass(earlyAccessFeatures || [], {
                    keys: ['name', 'description', 'stage'],
                    threshold: 0.3,
                })
            },
        ],

        filteredEarlyAccessFeatures: [
            (s) => [s.earlyAccessFeatures, s.searchTerm, s.featuresFuse],
            (
                earlyAccessFeatures: EarlyAccessFeatureType[],
                searchTerm: string,
                featuresFuse: EarlyAccessFeaturesFuse
            ): EarlyAccessFeatureType[] => {
                if (!searchTerm.trim()) {
                    return earlyAccessFeatures
                }

                const results = featuresFuse.search(searchTerm)
                return results.map((result) => result.item)
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
    }),
])
