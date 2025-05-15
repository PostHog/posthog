import equal from 'fast-deep-equal'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { getDefaultEventsQueryForTeam } from '~/queries/nodes/DataTable/defaultEventsQuery'
import { Node } from '~/queries/schema/schema-general'

import { getDefaultVisionHogEventsQuery } from './visionHogEventsDefaults'
import type { visionHogEventsSceneLogicType } from './visionHogEventsSceneLogicType'

export const visionHogEventsSceneLogic = kea<visionHogEventsSceneLogicType>([
    path(['products', 'vision_hog', 'frontend', 'visionHogEventsSceneLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeam']] })),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ savedQuery: [null as Node | null, { setQuery: (_, { query }) => query }] }),
    selectors({
        defaultQuery: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                const defaultSourceForTeam = currentTeam && getDefaultEventsQueryForTeam(currentTeam)
                const defaultForScene = getDefaultVisionHogEventsQuery()
                return defaultSourceForTeam ? { ...defaultForScene, source: defaultSourceForTeam } : defaultForScene
            },
        ],
        query: [(s) => [s.savedQuery, s.defaultQuery], (savedQuery, defaultQuery) => savedQuery || defaultQuery],
    }),
])
