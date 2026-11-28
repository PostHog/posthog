import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

import type { JourneySourceEnumApi, JourneyStepApi } from './frontend/generated/api.schemas'

export const manifest: ProductManifest = {
    name: 'User journeys',
    scenes: {
        UserJourneys: {
            name: 'User journeys',
            import: () => import('./frontend/scenes/UserJourneysScene/UserJourneysScene'),
            projectBased: true,
            description: 'Save the paths people take through your product and see how many sessions complete them.',
            iconType: 'insight/paths',
        },
        UserJourney: {
            name: 'User journey',
            import: () => import('./frontend/scenes/UserJourneyScene/UserJourneyScene'),
            projectBased: true,
            iconType: 'insight/paths',
        },
        UserJourneyEdit: {
            name: 'Edit user journey',
            import: () => import('./frontend/scenes/UserJourneyEditScene/UserJourneyEditScene'),
            projectBased: true,
            iconType: 'insight/paths',
        },
    },
    routes: {
        '/user-journeys': ['UserJourneys', 'userJourneys'],
        // Listed before `/user-journeys/:id` so that "new" never resolves as a journey ID.
        '/user-journeys/new': ['UserJourneyEdit', 'userJourneyNew'],
        '/user-journeys/:id': ['UserJourney', 'userJourney'],
        '/user-journeys/:id/edit': ['UserJourneyEdit', 'userJourneyEdit'],
    },
    redirects: {},
    urls: {
        userJourneys: (): string => '/user-journeys',
        /**
         * The create form, optionally prefilled. The toolbar links here to save a recorded flow, so the search params
         * are a contract: `name` and `description` are plain strings, `steps` is the JSON array of steps in the API
         * shape, and `source` is `toolbar` or `manual`.
         */
        userJourneyNew: (prefill?: {
            name?: string
            description?: string
            steps?: JourneyStepApi[]
            source?: JourneySourceEnumApi
        }): string =>
            combineUrl('/user-journeys/new', {
                name: prefill?.name,
                description: prefill?.description,
                steps: prefill?.steps,
                source: prefill?.source,
            }).url,
        userJourney: (id: string): string => `/user-journeys/${id}`,
        userJourneyEdit: (id: string): string => `/user-journeys/${id}/edit`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'User journeys',
            intents: [],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'insight/paths',
            href: urls.userJourneys(),
            searchKeywords: ['flows', 'user flows', 'paths', 'regressions'],
            flag: FEATURE_FLAGS.USER_JOURNEYS,
            tags: ['alpha'],
            sceneKey: 'UserJourneys',
        },
    ],
}
