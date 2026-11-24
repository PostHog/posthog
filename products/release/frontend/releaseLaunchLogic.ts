import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'lib/posthog-typed'
import { scheduleDateToProjectTzISO } from 'scenes/feature-flags/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import { LaunchFlag, defaultLaunchFlagIds, scheduleFlagLaunches } from './releaseLaunch'
import { releaseLogic } from './releaseLogic'

interface ReleaseLaunchLogicValues {
    currentProjectId: number | null
    currentTeam: TeamType | null
    launchOpen: boolean
    launchFlags: LaunchFlag[]
    launchDate: Dayjs
    selectedFlagIds: number[]
    failedFlagIds: number[]
    launching: boolean
    failedFlagKeys: string[]
    timezone: string
}

interface ReleaseLaunchLogicActions {
    loadScheduledChanges: () => void
    openLaunch: (flags: LaunchFlag[]) => { flags: LaunchFlag[] }
    closeLaunch: () => { value: true }
    setLaunchDate: (date: Dayjs) => { date: Dayjs }
    toggleLaunchFlag: (flagId: number, checked: boolean) => { flagId: number; checked: boolean }
    setSelectedFlagIds: (flagIds: number[]) => { flagIds: number[] }
    setFailedFlagIds: (flagIds: number[]) => { flagIds: number[] }
    launch: () => { value: true }
    launchDone: () => { value: true }
}

type releaseLaunchLogicType = MakeLogicType<ReleaseLaunchLogicValues, ReleaseLaunchLogicActions>

const nextLaunchDate = (): Dayjs => dayjs().add(1, 'day').hour(9).startOf('hour')

export const releaseLaunchLogic = kea<releaseLaunchLogicType>([
    path(['products', 'release', 'frontend', 'releaseLaunchLogic']),
    connect(() => ({
        values: [releaseLogic, ['currentProjectId'], teamLogic, ['currentTeam']],
        actions: [releaseLogic, ['loadScheduledChanges']],
    })),
    actions({
        openLaunch: (flags: LaunchFlag[]) => ({ flags }),
        closeLaunch: true,
        setLaunchDate: (date: Dayjs) => ({ date }),
        toggleLaunchFlag: (flagId: number, checked: boolean) => ({ flagId, checked }),
        setSelectedFlagIds: (flagIds: number[]) => ({ flagIds }),
        setFailedFlagIds: (flagIds: number[]) => ({ flagIds }),
        launch: true,
        launchDone: true,
    }),
    reducers({
        launchOpen: [false, { openLaunch: () => true, closeLaunch: () => false }],
        launchFlags: [[] as LaunchFlag[], { openLaunch: (_, { flags }) => flags }],
        launchDate: [nextLaunchDate(), { openLaunch: () => nextLaunchDate(), setLaunchDate: (_, { date }) => date }],
        selectedFlagIds: [
            [] as number[],
            {
                openLaunch: (_, { flags }) => defaultLaunchFlagIds(flags),
                setSelectedFlagIds: (_, { flagIds }) => flagIds,
                toggleLaunchFlag: (state, { flagId, checked }) =>
                    checked ? [...state.filter((id) => id !== flagId), flagId] : state.filter((id) => id !== flagId),
            },
        ],
        failedFlagIds: [[] as number[], { openLaunch: () => [], setFailedFlagIds: (_, { flagIds }) => flagIds }],
        launching: [false, { launch: () => true, launchDone: () => false }],
    }),
    selectors({
        failedFlagKeys: [
            (s) => [s.launchFlags, s.failedFlagIds],
            (launchFlags: LaunchFlag[], failedFlagIds: number[]): string[] =>
                launchFlags.filter((flag) => failedFlagIds.includes(flag.id)).map((flag) => flag.key),
        ],
        timezone: [(s) => [s.currentTeam], (currentTeam: TeamType | null): string => currentTeam?.timezone || 'UTC'],
    }),
    listeners(({ actions, values }) => ({
        openLaunch: ({ flags }) => {
            posthog.capture('release launch dialog opened', { flag_count: flags.length })
        },
        launch: async () => {
            const flagIds = values.selectedFlagIds
            if (!flagIds.length) {
                actions.launchDone()
                return
            }
            try {
                const { scheduledFlagIds, failedFlagIds } = await scheduleFlagLaunches(
                    String(values.currentProjectId),
                    flagIds,
                    scheduleDateToProjectTzISO(values.launchDate, values.timezone)
                )
                posthog.capture('release launch scheduled', {
                    flag_count: flagIds.length,
                    scheduled_count: scheduledFlagIds.length,
                    failed_count: failedFlagIds.length,
                })
                if (scheduledFlagIds.length) {
                    actions.loadScheduledChanges()
                }
                if (failedFlagIds.length) {
                    actions.setFailedFlagIds(failedFlagIds)
                    actions.setSelectedFlagIds(failedFlagIds)
                    lemonToast.error(
                        failedFlagIds.length === 1
                            ? 'One flag could not be scheduled. Try again.'
                            : `${failedFlagIds.length} flags could not be scheduled. Try again.`
                    )
                } else {
                    lemonToast.success(
                        scheduledFlagIds.length === 1
                            ? 'Scheduled 1 flag to turn on'
                            : `Scheduled ${scheduledFlagIds.length} flags to turn on`
                    )
                    actions.closeLaunch()
                }
            } finally {
                actions.launchDone()
            }
        },
    })),
])
