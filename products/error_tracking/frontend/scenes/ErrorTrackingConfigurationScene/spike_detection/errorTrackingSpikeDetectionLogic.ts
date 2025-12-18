import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

const DEFAULT_MULTIPLIER = 10
const MIN_MULTIPLIER = 2
const MAX_MULTIPLIER = 100

function clampInt(value: unknown, min: number, max: number, fallback: number): number {
    const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
    if (!Number.isFinite(parsed)) {
        return fallback
    }
    const rounded = Math.round(parsed)
    return Math.min(max, Math.max(min, rounded))
}

function getMultiplierFromTeam(currentTeam: TeamType | null): number {
    return clampInt(currentTeam?.error_tracking_spike_detection_multiplier, MIN_MULTIPLIER, MAX_MULTIPLIER, DEFAULT_MULTIPLIER)
}

export const errorTrackingSpikeDetectionLogic = kea([
    path(['products', 'error_tracking', 'configuration', 'spike_detection', 'errorTrackingSpikeDetectionLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam', 'loadCurrentTeamSuccess']],
    })),
    actions({
        setMultiplier: (multiplier: number) => ({ multiplier }),
        syncFromTeam: (multiplier: number) => ({ multiplier }),
        persistSettings: true,
    }),
    reducers(() => ({
        multiplier: [
            DEFAULT_MULTIPLIER,
            {
                setMultiplier: (_, { multiplier }) =>
                    clampInt(multiplier, MIN_MULTIPLIER, MAX_MULTIPLIER, DEFAULT_MULTIPLIER),
                syncFromTeam: (_, { multiplier }) => multiplier,
            },
        ],
    })),
    selectors({
        multiplierConfig: [
            () => [],
            () => ({
                min: MIN_MULTIPLIER,
                max: MAX_MULTIPLIER,
            }),
        ],
    }),
    afterMount(({ actions, values }) => {
        actions.syncFromTeam(getMultiplierFromTeam(values.currentTeam))
    }),
    listeners(({ actions }) => ({
        loadCurrentTeamSuccess: ({ currentTeam }: { currentTeam: TeamType }) => {
            actions.syncFromTeam(getMultiplierFromTeam(currentTeam))
        },
        setMultiplier: () => actions.persistSettings(),
    })),
    listeners(({ actions, values }) => ({
        persistSettings: async (_, breakpoint) => {
            await breakpoint(1000)
            actions.updateCurrentTeam({
                error_tracking_spike_detection_multiplier: values.multiplier,
            })
        },
    })),
])
