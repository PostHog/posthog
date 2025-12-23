import { actions, connect, kea, path, reducers } from 'kea'

import { clamp } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import type { errorTrackingSpikeDetectionLogicType } from './errorTrackingSpikeDetectionLogicType'

export const DEFAULT_MULTIPLIER = 10
export const MIN_MULTIPLIER = 2
export const MAX_MULTIPLIER = 100

export const errorTrackingSpikeDetectionLogic = kea<errorTrackingSpikeDetectionLogicType>([
    path(['products', 'error_tracking', 'configuration', 'spike_detection', 'errorTrackingSpikeDetectionLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam', 'loadCurrentTeamSuccess']],
    })),
    actions({
        setMultiplier: (multiplier: number) => ({ multiplier }),
    }),
    reducers(() => ({
        multiplier: [
            DEFAULT_MULTIPLIER,
            {
                setMultiplier: (_, { multiplier }) => clamp(Math.round(multiplier), MIN_MULTIPLIER, MAX_MULTIPLIER),
            },
        ],
    })),
])
