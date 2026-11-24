import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'lib/posthog-typed'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import {
    LaunchFailure,
    LaunchFlag,
    defaultLaunchFlagIds,
    isLaunchInPast,
    launchTimeISO,
    scheduleFlagLaunches,
} from './releaseLaunch'
import { releaseLogic } from './releaseLogic'

interface ReleaseLaunchLogicValues {
    currentProjectId: number | null
    currentTeam: TeamType | null
    launchOpen: boolean
    launchFlags: LaunchFlag[]
    launchDate: Dayjs
    selectedFlagIds: number[]
    failures: LaunchFailure[]
    launching: boolean
    failedFlags: (LaunchFailure & { key: string })[]
    launchInPast: boolean
    timezone: string
}

interface ReleaseLaunchLogicActions {
    loadScheduledChanges: () => void
    openLaunch: (flags: LaunchFlag[]) => { flags: LaunchFlag[] }
    closeLaunch: () => { value: true }
    setLaunchDate: (date: Dayjs) => { date: Dayjs }
    toggleLaunchFlag: (flagId: number, checked: boolean) => { flagId: number; checked: boolean }
    setSelectedFlagIds: (flagIds: number[]) => { flagIds: number[] }
    setFailures: (failures: LaunchFailure[]) => { failures: LaunchFailure[] }
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
        setFailures: (failures: LaunchFailure[]) => ({ failures }),
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
        failures: [[] as LaunchFailure[], { openLaunch: () => [], setFailures: (_, { failures }) => failures }],
        launching: [false, { launch: () => true, launchDone: () => false }],
    }),
    selectors({
        failedFlags: [
            (s) => [s.launchFlags, s.failures],
            (launchFlags: LaunchFlag[], failures: LaunchFailure[]): (LaunchFailure & { key: string })[] =>
                failures.map((failure) => ({
                    ...failure,
                    key: launchFlags.find((flag) => flag.id === failure.flagId)?.key ?? String(failure.flagId),
                })),
        ],
        timezone: [(s) => [s.currentTeam], (currentTeam: TeamType | null): string => currentTeam?.timezone || 'UTC'],
        launchInPast: [
            (s) => [s.launchDate, s.timezone],
            (launchDate: Dayjs, timezone: string): boolean => isLaunchInPast(launchDate, timezone),
        ],
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
            if (isLaunchInPast(values.launchDate, values.timezone)) {
                lemonToast.error('Pick a launch time in the future.')
                actions.launchDone()
                return
            }
            try {
                const { scheduledFlagIds, failures } = await scheduleFlagLaunches(
                    String(values.currentProjectId),
                    flagIds,
                    launchTimeISO(values.launchDate, values.timezone)
                )
                posthog.capture('release launch scheduled', {
                    flag_count: flagIds.length,
                    scheduled_count: scheduledFlagIds.length,
                    failed_count: failures.length,
                    pending_approval_count: failures.filter((failure) => failure.pendingApproval).length,
                })
                if (scheduledFlagIds.length) {
                    actions.loadScheduledChanges()
                }
                if (failures.length) {
                    actions.setFailures(failures)
                    actions.setSelectedFlagIds(
                        failures.filter((failure) => !failure.pendingApproval).map((failure) => failure.flagId)
                    )
                    lemonToast.error(
                        failures.length === 1
                            ? 'One flag could not be scheduled.'
                            : `${failures.length} flags could not be scheduled.`
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
