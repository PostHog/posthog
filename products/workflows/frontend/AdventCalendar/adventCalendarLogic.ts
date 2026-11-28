import { actions, afterMount, connect, kea, listeners, MakeLogicType, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import * as api from 'products/workflows/frontend/generated/api'
import {
    AdventCalendarAnswerApi,
    AdventCalendarDayEnumApi,
    AdventCalendarOptionEnumApi,
    AdventCalendarResultsApi,
} from 'products/workflows/frontend/generated/api.schemas'

import type { PreflightStatus, UserType } from '../../../../frontend/src/types'
import { adventQuestionBefore, AdventReward } from './adventContent'
import { AdventRewards, drawAdventRewards } from './adventDraw'
import {
    AdventDoor,
    adventDoorCenter,
    AdventGraph,
    AdventPoint,
    AdventProgress,
    buildAdventGraph,
    EMPTY_ADVENT_PROGRESS,
    mergeAdventProgress,
    openDoors,
} from './adventGraph'
import { adventHasWorkflows } from './adventHasWorkflows'
import {
    cleanProgressByUser,
    cleanTicketsByUser,
    PROGRESS_STORAGE_KEY,
    reachableProgress,
    storedProgressByUser,
    storedTicketsByUser,
    PENDING_TICKETS_STORAGE_KEY,
    TICKETS_STORAGE_KEY,
} from './adventProgressStorage'
import { adventOpenedOnItsDay, adventTicketDays } from './adventTickets'
import { adventPicksDay, adventToday } from './adventToday'

// pinned: analytics event names and property keys. Usage insights query them, so a rename breaks them.
const EVENTS = {
    viewed: 'workflows advent calendar viewed',
    doorOpened: 'workflows advent door opened',
    answerPicked: 'workflows advent answer picked',
    tipClicked: 'workflows advent tip clicked',
    shared: 'workflows advent shared',
} as const

const CLOCK_REFRESH_MS = 60_000

// A preview picked with ?day= sends nothing, so the usage insights count real opens only.
function captureLive(isLive: boolean, event: string, properties: Record<string, boolean | number | string>): void {
    if (isLive) {
        posthog.capture(event, properties)
    }
}

// The doors past a question on the branch its answer did not take. They puff away as the answered door opens.
function doorsNotTaken(graph: AdventGraph, question: AdventDoor, optionIndex: number): AdventDoor[] {
    const notTaken = optionIndex === 0 ? 'lower' : 'upper'
    return graph.doors.filter(
        (candidate) => adventQuestionBefore(candidate.day) === question.day && candidate.id.endsWith(notTaken)
    )
}

function isPollDay(day: number): day is AdventCalendarDayEnumApi {
    return (Object.values(AdventCalendarDayEnumApi) as number[]).includes(day)
}

function isPollOption(optionId: string): optionId is AdventCalendarOptionEnumApi {
    return (Object.values(AdventCalendarOptionEnumApi) as string[]).includes(optionId)
}

function pollAnswerOf(day: number, optionId: string): AdventCalendarAnswerApi | null {
    return isPollDay(day) && isPollOption(optionId) ? { day, option: optionId } : null
}

async function resultsOrNull(request: Promise<AdventCalendarResultsApi>): Promise<AdventCalendarResultsApi | null> {
    try {
        return await request
    } catch {
        return null
    }
}

function mergeResults(
    current: AdventCalendarResultsApi | null,
    next: AdventCalendarResultsApi | null
): AdventCalendarResultsApi | null {
    if (!current?.questions || !next?.questions) {
        return next ?? current
    }
    const known = new Map(current.questions.map((question) => [question.day, question]))
    return {
        ...next,
        questions: next.questions.map((question) => {
            const answered = known.get(question.day)
            return !question.answer && answered?.answer ? answered : question
        }),
    }
}

export type AdventPollShares = Record<number, Record<string, number>>

function sharesOfAnswered(results: AdventCalendarResultsApi | null, picks: Record<number, string>): AdventPollShares {
    const answered = (results?.questions ?? []).filter(
        (question) => question.answer && question.answer === picks[question.day]
    )
    return Object.fromEntries(
        answered.map((question) => [
            question.day,
            Object.fromEntries(question.shares.map((share) => [share.option, share.share])),
        ])
    )
}

export interface AdventSnowPuff extends AdventPoint {
    id: string
}

function withChange(
    state: Record<string, AdventProgress>,
    stored: unknown,
    userUuid: string,
    change: AdventProgress
): Record<string, AdventProgress> {
    const latest = cleanProgressByUser(stored)
    const cached = cleanProgressByUser(state)
    const uuids = new Set([...Object.keys(latest), ...Object.keys(cached), userUuid])
    return Object.fromEntries(
        [...uuids].map((uuid) => [
            uuid,
            [cached[uuid], uuid === userUuid ? change : undefined].reduce<AdventProgress>(
                (merged, next) => (next ? mergeAdventProgress(merged, next) : merged),
                latest[uuid] ?? EMPTY_ADVENT_PROGRESS
            ),
        ])
    )
}

function withTicket(
    state: Record<string, number[]>,
    stored: unknown,
    userUuid: string,
    day: number | null
): Record<string, number[]> {
    const latest = cleanTicketsByUser(stored)
    const cached = cleanTicketsByUser(state)
    const uuids = new Set([...Object.keys(latest), ...Object.keys(cached), ...(day === null ? [] : [userUuid])])
    return Object.fromEntries(
        [...uuids].map((uuid) => {
            const days = [
                ...(latest[uuid] ?? []),
                ...(cached[uuid] ?? []),
                ...(uuid === userUuid && day !== null ? [day] : []),
            ]
            return [uuid, [...new Set(days)].sort((x, y) => x - y)]
        })
    )
}

const withDay = (days: number[], day: number): number[] => (days.includes(day) ? days : [...days, day])
const withoutDay = (days: number[], day: number): number[] => days.filter((pending) => pending !== day)

function withPendingDays(
    state: unknown,
    userUuid: string,
    update: (days: number[]) => number[]
): Record<string, number[]> {
    const pending = cleanTicketsByUser(state)
    return { ...pending, [userUuid]: update(pending[userUuid] ?? []) }
}

function isRefused(error: unknown): boolean {
    return error instanceof ApiError && !!error.status && error.status < 500 && error.status !== 429
}

function prefersReducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function rewardsBehind(door: AdventDoor): AdventReward[] {
    const optionRewards = door.question?.options.map((option) => option.reward) ?? []
    return [door.reward, ...optionRewards].filter((reward): reward is AdventReward => !!reward)
}

export function adventImagesToPreload(graph: AdventGraph): string[] {
    const nextDay = graph.doors.find((door) => door.status === 'locked')?.day
    const doors = graph.doors.filter((door) => door.status !== 'locked' || door.day === nextDay)
    return [...new Set(doors.flatMap(rewardsBehind).map((reward) => reward.image.src))]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface adventCalendarLogicValues {
    preflight: PreflightStatus | null // preflightLogic
    currentProjectId: number | null // projectLogic
    searchParams: Record<string, any> // router
    user: UserType | null // userLogic
    graph: AdventGraph
    isLive: boolean
    localDate: number
    openCount: number
    pendingTicketsByUser: Record<string, number[]>
    pollReply: {
        read: number
        results: AdventCalendarResultsApi | null
    }
    pollResults: AdventCalendarResultsApi | null
    pollShares: AdventPollShares
    previewProgress: AdventProgress
    previewTicketDays: number[]
    progress: AdventProgress
    progressByUser: Record<string, AdventProgress>
    revealingDoor: AdventDoor | null
    revealingDoorId: string | null
    rewards: AdventRewards
    selectedDoor: AdventDoor | null
    selectedDoorId: string | null
    snowPuffs: AdventSnowPuff[]
    ticketDays: number[]
    ticketFlight: number | null
    tickets: number
    ticketsByUser: Record<string, number[]>
    ticketsShown: number
    today: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface adventCalendarLogicActions {
    loadUserSuccess: (
        user: UserType | null,
        payload?:
            | {
                  resetOnFailure: boolean | undefined
              }
            | undefined
    ) => {
        payload?: {
            resetOnFailure: boolean | undefined
        }
        user: UserType | null
    } // userLogic
    activateDoor: (doorId: string) => {
        doorId: string
    }
    answerDoor: (
        doorId: string,
        optionId: string
    ) => {
        doorId: string
        optionId: string
    }
    clearSelection: () => {
        value: true
    }
    clearSnowPuffs: () => {
        value: true
    }
    clickTip: (day: number) => {
        day: number
    }
    finishReveal: () => {
        value: true
    }
    landTicket: () => {
        value: true
    }
    loadPollResults: () => {
        value: true
    }
    mergeStoredTickets: () => {
        stored: unknown
    }
    openDoor: (
        userUuid: string,
        day: number,
        optionId: string | null,
        isLive: boolean,
        isOnTime: boolean
    ) => {
        day: number
        isLive: boolean
        isOnTime: boolean
        optionId: string | null
        stored: unknown
        userUuid: string
    }
    pinDoor: (doorId: string) => {
        doorId: string
    }
    preloadImages: () => {
        value: true
    }
    puffSnow: (puffs: AdventSnowPuff[]) => {
        puffs: AdventSnowPuff[]
    }
    receivePollResults: (
        results: AdventCalendarResultsApi,
        read: number
    ) => {
        read: number
        results: AdventCalendarResultsApi
    }
    refreshClock: () => {
        localDate: number
    }
    resumePendingTickets: () => {
        value: true
    }
    savePollAnswer: (answer: AdventCalendarAnswerApi) => {
        answer: AdventCalendarAnswerApi
    }
    settleTicket: (
        userUuid: string,
        day: number,
        isOnTime: boolean,
        wasGuessedOnTime: boolean
    ) => {
        day: number
        isOnTime: boolean
        stored: unknown
        userUuid: string
        wasGuessedOnTime: boolean
    }
    share: () => {
        value: true
    }
    startReveal: (doorId: string) => {
        doorId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface adventCalendarLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        pollResults: (pollReply: {
            read: number
            results: AdventCalendarResultsApi | null
        }) => AdventCalendarResultsApi | null
        progress: (
            progressByUser: Record<string, AdventProgress>,
            user: UserType | null,
            previewProgress: AdventProgress,
            isLive: boolean
        ) => AdventProgress
        today: (
            localDate: number,
            searchParams: Record<string, any>,
            user: UserType | null,
            preflight: PreflightStatus | null
        ) => number
        isLive: (
            localDate: number,
            searchParams: Record<string, any>,
            user: UserType | null,
            preflight: PreflightStatus | null
        ) => boolean
        rewards: (user: UserType | null) => AdventRewards
        graph: (progress: AdventProgress, today: number, rewards: AdventRewards) => AdventGraph
        pollShares: (pollResults: AdventCalendarResultsApi | null, progress: AdventProgress) => AdventPollShares
        openCount: (graph: AdventGraph) => number
        ticketDays: (
            progress: AdventProgress,
            ticketsByUser: Record<string, number[]>,
            pendingTicketsByUser: Record<string, number[]>,
            previewTicketDays: number[],
            user: UserType | null,
            isLive: boolean
        ) => number[]
        tickets: (ticketDays: number[]) => number
        ticketsShown: (tickets: number, ticketDays: number[], ticketFlight: number | null) => number
        selectedDoor: (graph: AdventGraph, selectedDoorId: string | null) => AdventDoor | null
        revealingDoor: (graph: AdventGraph, revealingDoorId: string | null) => AdventDoor | null
    }
}

export type adventCalendarLogicType = MakeLogicType<
    adventCalendarLogicValues,
    adventCalendarLogicActions,
    Record<string, any>,
    adventCalendarLogicMeta
>

export const adventCalendarLogic = kea<adventCalendarLogicType>([
    path(['products', 'workflows', 'frontend', 'AdventCalendar', 'adventCalendarLogic']),
    connect(() => ({
        values: [
            router,
            ['searchParams'],
            preflightLogic,
            ['preflight'],
            userLogic,
            ['user'],
            projectLogic,
            ['currentProjectId'],
        ],
        actions: [userLogic, ['loadUserSuccess']],
    })),
    actions({
        activateDoor: (doorId: string) => ({ doorId }),
        pinDoor: (doorId: string) => ({ doorId }),
        answerDoor: (doorId: string, optionId: string) => ({ doorId, optionId }),
        openDoor: (userUuid: string, day: number, optionId: string | null, isLive: boolean, isOnTime: boolean) => ({
            userUuid,
            day,
            optionId,
            isLive,
            isOnTime,
            stored: storedProgressByUser(),
        }),
        landTicket: true,
        resumePendingTickets: true,
        mergeStoredTickets: () => ({ stored: storedTicketsByUser() }),
        settleTicket: (userUuid: string, day: number, isOnTime: boolean, wasGuessedOnTime: boolean) => ({
            userUuid,
            day,
            isOnTime,
            wasGuessedOnTime,
            stored: storedTicketsByUser(),
        }),
        refreshClock: () => {
            const now = new Date()
            return { localDate: new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() }
        },
        startReveal: (doorId: string) => ({ doorId }),
        finishReveal: true,
        clearSelection: true,
        puffSnow: (puffs: AdventSnowPuff[]) => ({ puffs }),
        clearSnowPuffs: true,
        clickTip: (day: number) => ({ day }),
        loadPollResults: true,
        savePollAnswer: (answer: AdventCalendarAnswerApi) => ({ answer }),
        receivePollResults: (results: AdventCalendarResultsApi, read: number) => ({ results, read }),
        share: true,
        preloadImages: true,
    }),
    reducers({
        pollReply: [
            { read: 0, results: null } as { read: number; results: AdventCalendarResultsApi | null },
            {
                receivePollResults: (state, { results, read }) =>
                    read < state.read
                        ? { ...state, results: mergeResults(results, state.results) }
                        : { read, results: mergeResults(state.results, results) },
            },
        ],
        progressByUser: [
            {} as Record<string, AdventProgress>,
            { persist: true, storageKey: PROGRESS_STORAGE_KEY },
            {
                openDoor: (state, { userUuid, day, optionId, stored, isLive }) =>
                    isLive
                        ? withChange(state, stored, userUuid, {
                              opened: [day],
                              answers: optionId ? { [day]: optionId } : {},
                          })
                        : state,
            },
        ],
        ticketsByUser: [
            {} as Record<string, number[]>,
            { persist: true, storageKey: TICKETS_STORAGE_KEY },
            {
                settleTicket: (state, { userUuid, day, isOnTime, stored }) =>
                    withTicket(state, stored, userUuid, isOnTime ? day : null),
                mergeStoredTickets: (state, { stored }) => withTicket(state, stored, '', null),
            },
        ],
        pendingTicketsByUser: [
            {} as Record<string, number[]>,
            { persist: true, storageKey: PENDING_TICKETS_STORAGE_KEY },
            {
                openDoor: (state, { userUuid, day, isLive, isOnTime }) =>
                    isLive && isOnTime ? withPendingDays(state, userUuid, (days) => withDay(days, day)) : state,
                settleTicket: (state, { userUuid, day }) =>
                    withPendingDays(state, userUuid, (days) => withoutDay(days, day)),
            },
        ],
        previewTicketDays: [
            [] as number[],
            {
                openDoor: (state, { day, isLive, isOnTime }) => (isLive ? [] : isOnTime ? withDay(state, day) : state),
            },
        ],
        previewProgress: [
            EMPTY_ADVENT_PROGRESS,
            {
                openDoor: (state, { day, optionId, isLive }) =>
                    isLive
                        ? EMPTY_ADVENT_PROGRESS
                        : mergeAdventProgress(state, {
                              opened: [day],
                              answers: optionId ? { [day]: optionId } : {},
                          }),
            },
        ],
        localDate: [
            0,
            {
                refreshClock: (_, { localDate }) => localDate,
            },
        ],
        selectedDoorId: [
            null as string | null,
            {
                activateDoor: (_, { doorId }) => doorId,
                pinDoor: (_, { doorId }) => doorId,
                clearSelection: () => null,
            },
        ],
        revealingDoorId: [
            null as string | null,
            {
                startReveal: (_, { doorId }) => doorId,
                finishReveal: () => null,
            },
        ],
        snowPuffs: [
            [] as AdventSnowPuff[],
            {
                puffSnow: (_, { puffs }) => puffs,
                clearSnowPuffs: () => [],
            },
        ],
        ticketFlight: [
            null as number | null,
            {
                openDoor: (state, { day, isOnTime }) => (isOnTime ? day : state),
                settleTicket: (state, { day, isOnTime, wasGuessedOnTime }) =>
                    isOnTime && !wasGuessedOnTime ? day : !isOnTime && state === day ? null : state,
                landTicket: () => null,
            },
        ],
    }),
    selectors({
        pollResults: [
            (s) => [s.pollReply],
            (pollReply: adventCalendarLogicValues['pollReply']): AdventCalendarResultsApi | null => pollReply.results,
        ],
        progress: [
            (s) => [s.progressByUser, s.user, s.previewProgress, s.isLive],
            (
                progressByUser: adventCalendarLogicValues['progressByUser'],
                user: adventCalendarLogicValues['user'],
                previewProgress: adventCalendarLogicValues['previewProgress'],
                isLive: adventCalendarLogicValues['isLive']
            ): AdventProgress => {
                const stored = cleanProgressByUser(progressByUser)[user?.uuid ?? ''] ?? EMPTY_ADVENT_PROGRESS
                return reachableProgress(isLive ? stored : mergeAdventProgress(stored, previewProgress))
            },
        ],
        today: [
            (s) => [s.localDate, s.searchParams, s.user, s.preflight],
            (
                localDate: adventCalendarLogicValues['localDate'],
                searchParams: adventCalendarLogicValues['searchParams'],
                user: adventCalendarLogicValues['user'],
                preflight: adventCalendarLogicValues['preflight']
            ): number =>
                adventToday(new Date(localDate), {
                    requestedDay: searchParams.day != null ? String(searchParams.day) : null,
                    canPickDay: !!user?.is_staff || !!preflight?.is_debug,
                }),
        ],
        isLive: [
            (s) => [s.localDate, s.searchParams, s.user, s.preflight],
            (
                localDate: adventCalendarLogicValues['localDate'],
                searchParams: adventCalendarLogicValues['searchParams'],
                user: adventCalendarLogicValues['user'],
                preflight: adventCalendarLogicValues['preflight']
            ): boolean =>
                !adventPicksDay(new Date(localDate), {
                    requestedDay: searchParams.day != null ? String(searchParams.day) : null,
                    canPickDay: !!user?.is_staff || !!preflight?.is_debug,
                }),
        ],
        rewards: [
            (s) => [s.user],
            (user: adventCalendarLogicValues['user']): AdventRewards => drawAdventRewards(user?.uuid ?? ''),
        ],
        graph: [
            (s) => [s.progress, s.today, s.rewards],
            (
                progress: adventCalendarLogicValues['progress'],
                today: adventCalendarLogicValues['today'],
                rewards: adventCalendarLogicValues['rewards']
            ): AdventGraph => buildAdventGraph(progress, today, rewards),
        ],
        pollShares: [
            (s) => [s.pollResults, s.progress],
            (
                pollResults: adventCalendarLogicValues['pollResults'],
                progress: adventCalendarLogicValues['progress']
            ): AdventPollShares => sharesOfAnswered(pollResults, progress.answers),
        ],
        openCount: [(s) => [s.graph], (graph: adventCalendarLogicValues['graph']): number => openDoors(graph).length],
        ticketDays: [
            (s) => [s.progress, s.ticketsByUser, s.pendingTicketsByUser, s.previewTicketDays, s.user, s.isLive],
            (
                progress: adventCalendarLogicValues['progress'],
                ticketsByUser: Record<string, number[]>,
                pendingTicketsByUser: Record<string, number[]>,
                previewTicketDays: number[],
                user: adventCalendarLogicValues['user'],
                isLive: adventCalendarLogicValues['isLive']
            ): number[] => {
                const confirmed = cleanTicketsByUser(ticketsByUser)[user?.uuid ?? ''] ?? []
                const pending = cleanTicketsByUser(pendingTicketsByUser)[user?.uuid ?? ''] ?? []
                return adventTicketDays(progress.opened, [...confirmed, ...(isLive ? pending : previewTicketDays)])
            },
        ],
        tickets: [
            (s) => [s.ticketDays],
            (ticketDays: adventCalendarLogicValues['ticketDays']): number => ticketDays.length,
        ],
        ticketsShown: [
            (s) => [s.tickets, s.ticketDays, s.ticketFlight],
            (
                tickets: adventCalendarLogicValues['tickets'],
                ticketDays: adventCalendarLogicValues['ticketDays'],
                ticketFlight: number | null
            ): number => tickets - (ticketFlight !== null && ticketDays.includes(ticketFlight) ? 1 : 0),
        ],
        selectedDoor: [
            (s) => [s.graph, s.selectedDoorId],
            (
                graph: adventCalendarLogicValues['graph'],
                selectedDoorId: adventCalendarLogicValues['selectedDoorId']
            ): AdventDoor | null => graph.doors.find((door) => door.id === selectedDoorId) ?? null,
        ],
        revealingDoor: [
            (s) => [s.graph, s.revealingDoorId],
            (
                graph: adventCalendarLogicValues['graph'],
                revealingDoorId: adventCalendarLogicValues['revealingDoorId']
            ): AdventDoor | null =>
                graph.doors.find((door) => door.id === revealingDoorId && door.status === 'open') ?? null,
        ],
    }),
    listeners(({ actions, values, cache }) => {
        const receive = async (request: Promise<AdventCalendarResultsApi>): Promise<void> => {
            const read = (cache.resultReads = (cache.resultReads ?? 0) + 1)
            const mount = cache.disposables
            cache.pendingReads = (cache.pendingReads ?? 0) + 1
            cache.readsOverlapped ||= cache.pendingReads > 1
            const results = await resultsOrNull(request)
            cache.pendingReads -= 1
            if (results && !mount.isDisposed) {
                actions.receivePollResults(results, read)
            }
            if (cache.pendingReads === 0) {
                const reread = cache.readsOverlapped && !cache.disposables.isDisposed
                cache.readsOverlapped = false
                if (reread) {
                    actions.loadPollResults()
                }
            }
        }
        const readyDoor = (doorId: string): AdventDoor | null => {
            if (values.revealingDoor) {
                return null
            }
            const door = values.graph.doors.find((candidate) => candidate.id === doorId)
            return door?.status === 'ready' ? door : null
        }
        const confirmTicket = (userUuid: string, day: number, wasGuessedOnTime: boolean): void => {
            const settle = (isOnServerDay: boolean): void => {
                if (adventCalendarLogic.isMounted()) {
                    actions.settleTicket(userUuid, day, isOnServerDay, wasGuessedOnTime)
                }
            }
            const hoggy = values.graph.doors.find((door) => door.day === day && door.status === 'open')?.reward
            if (!hoggy) {
                settle(false)
                return
            }
            const utcOffsetMinutes = -new Date().getTimezoneOffset()
            void api
                .workflowAdventCalendarOpen(String(values.currentProjectId), {
                    day,
                    hoggy: hoggy.id,
                    utc_offset_minutes: utcOffsetMinutes,
                })
                .then(
                    (open) =>
                        settle(
                            adventOpenedOnItsDay(
                                day,
                                new Date(open.opened_at),
                                open.utc_offset_minutes ?? utcOffsetMinutes
                            )
                        ),
                    (error) => {
                        if (isRefused(error)) {
                            settle(false)
                        }
                    }
                )
        }
        const isOnTime = (day: number): boolean => {
            const now = new Date()
            return !values.isLive || adventOpenedOnItsDay(day, now, -now.getTimezoneOffset())
        }
        return {
            loadPollResults: () => receive(api.workflowAdventCalendarResults(String(values.currentProjectId))),
            savePollAnswer: ({ answer }) =>
                receive(api.workflowAdventCalendarAnswer(String(values.currentProjectId), answer)),
            activateDoor: ({ doorId }) => {
                const door = readyDoor(doorId)
                if (door && !door.question) {
                    actions.openDoor(values.user?.uuid ?? '', door.day, null, values.isLive, isOnTime(door.day))
                    if (!prefersReducedMotion()) {
                        actions.startReveal(door.id)
                    }
                }
            },
            answerDoor: ({ doorId, optionId }) => {
                const door = readyDoor(doorId)
                const index = door?.question?.options.findIndex((option) => option.id === optionId) ?? -1
                if (!door || index < 0) {
                    return
                }
                const uuid = values.user?.uuid ?? ''
                const storedPick = cleanProgressByUser(storedProgressByUser())[uuid]?.answers[door.day]
                if (storedPick) {
                    actions.openDoor(uuid, door.day, storedPick, values.isLive, isOnTime(door.day))
                    actions.loadPollResults()
                    return
                }
                const vanishing = doorsNotTaken(values.graph, door, index)
                captureLive(values.isLive, EVENTS.answerPicked, { day: door.day, option: optionId })
                actions.openDoor(uuid, door.day, optionId, values.isLive, isOnTime(door.day))
                const answer = pollAnswerOf(door.day, values.progress.answers[door.day] ?? optionId)
                if (answer && values.isLive) {
                    actions.savePollAnswer(answer)
                }
                if (!prefersReducedMotion()) {
                    actions.puffSnow(
                        vanishing.map((candidate) => ({ id: candidate.id, ...adventDoorCenter(candidate) }))
                    )
                    actions.startReveal(door.id)
                }
            },
            openDoor: ({ userUuid, day, isLive, isOnTime }) => {
                captureLive(isLive, EVENTS.doorOpened, { day, on_time: isOnTime })
                if (isLive) {
                    confirmTicket(userUuid, day, isOnTime)
                }
                actions.preloadImages()
            },
            resumePendingTickets: () => {
                const userUuid = values.user?.uuid
                if (values.isLive && userUuid) {
                    for (const day of cleanTicketsByUser(values.pendingTicketsByUser)[userUuid] ?? []) {
                        confirmTicket(userUuid, day, true)
                    }
                }
            },
            clickTip: ({ day }) => {
                posthog.capture(EVENTS.tipClicked, { day })
            },
            share: () => {
                posthog.capture(EVENTS.shared)
            },
            loadUserSuccess: () => {
                actions.preloadImages()
                actions.resumePendingTickets()
            },
            preloadImages: () => {
                if (!values.user) {
                    return
                }
                cache.preloaded ??= new Map<string, HTMLImageElement>()
                for (const src of adventImagesToPreload(values.graph)) {
                    if (src && !cache.preloaded.has(src)) {
                        const image = new Image()
                        image.src = src
                        cache.preloaded.set(src, image)
                    }
                }
            },
        }
    }),
    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            actions.refreshClock()
            const timer = window.setInterval(() => actions.refreshClock(), CLOCK_REFRESH_MS)
            return () => window.clearInterval(timer)
        }, 'clock')
        posthog.capture(EVENTS.viewed, { has_workflows: adventHasWorkflows() })
        actions.preloadImages()
        actions.loadPollResults()
        cache.disposables.add(() => {
            const onStorage = (event: StorageEvent): void => {
                if (event.key === TICKETS_STORAGE_KEY) {
                    actions.mergeStoredTickets()
                }
            }
            window.addEventListener('storage', onStorage)
            return () => window.removeEventListener('storage', onStorage)
        }, 'tickets')
        cache.disposables.add(() => {
            const onOnline = (): void => actions.resumePendingTickets()
            window.addEventListener('online', onOnline)
            return () => window.removeEventListener('online', onOnline)
        }, 'online')
        actions.resumePendingTickets()
    }),
])
