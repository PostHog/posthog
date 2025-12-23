import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { clamp } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

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
        persistSettings: true,
    }),
    reducers(() => ({
        multiplier: [
            DEFAULT_MULTIPLIER as number,
            {
                setMultiplier: (_, { multiplier }) => clamp(Math.round(multiplier), MIN_MULTIPLIER, MAX_MULTIPLIER),
            },
        ],
    })),
    subscriptions(({ actions }) => ({
        currentTeam: (currentTeam: TeamType) => {
            actions.setMultiplier(currentTeam?.error_tracking_spike_detection_multiplier ?? DEFAULT_MULTIPLIER)
        },
    })),
    afterMount(({ actions, values }) => {
        actions.setMultiplier(values.currentTeam?.error_tracking_spike_detection_multiplier ?? DEFAULT_MULTIPLIER)
    }),
    listeners(({ actions, values }) => ({
        setMultiplier: () => actions.persistSettings(),
        persistSettings: async (_, breakpoint) => {
            await breakpoint(1000)
            actions.updateCurrentTeam({
                error_tracking_spike_detection_multiplier: values.multiplier,
            })
        },
    })),
])
