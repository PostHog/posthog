import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createPersistHydrationGate } from '@/lib/persistHydration'
import { MCP_VIA } from '@/model/agent'
import type { ActivityEvent, DecisionAnswer, ReportPriority } from '@/model/types'
import {
    DISMISSAL_REASON_OPTIONS,
    type DismissReason,
    RESOLVE_REASON_OPTIONS,
    type ResolveReason,
} from '@/model/verdictReasons'

import { DEMO_AGENT, DEMO_USER_NAME } from './briefings'
import { DEMO_PEOPLE } from './fixtures'

const REFRESH_MS = 450
const DEMO_FROM_ENV = __DEV__ && process.env.EXPO_PUBLIC_DEMO_MODE === '1'

export type DemoLogTag = 'handoff' | 'decision' | 'snooze' | 'reviewers' | 'priority' | 'verdict'

export interface DemoLogEntry extends ActivityEvent {
    tag: DemoLogTag
}

export interface DemoMutableState {
    /** Epoch ms that fixture times are relative to. */
    anchor: number
    handed: Record<string, string>
    decisions: Record<string, DecisionAnswer>
    snoozed: Record<string, string>
    closed: Record<string, 'resolved' | 'dismissed'>
    /** An explicit value overrides the fixture's read state. */
    read: Record<string, boolean>
    reviewers: Record<string, string[]>
    priorities: Record<string, ReportPriority>
    /** Demo session ids the person archived from the Chats list. */
    archivedChats: Record<string, true>
    log: Record<string, DemoLogEntry[]>
    isRefreshing: boolean
}

export interface DemoSnoozeLabels {
    row: string
    activity: string
}

export interface DemoModeState extends DemoMutableState {
    enabled: boolean
    setEnabled: (enabled: boolean) => void
    reset: () => void
    refresh: () => void
    handOff: (reportId: string) => void
    answer: (reportId: string, answer: DecisionAnswer) => void
    undoAnswer: (reportId: string) => void
    snooze: (reportId: string, labels: DemoSnoozeLabels) => void
    resolve: (reportId: string, reason: ResolveReason) => void
    dismiss: (reportId: string, reason: DismissReason) => void
    setReviewers: (reportId: string, uuids: string[]) => void
    setPriority: (reportId: string, priority: ReportPriority) => void
    markRead: (reportId: string) => void
    markUnread: (reportId: string) => void
    archiveChat: (taskId: string) => void
    unarchiveChat: (taskId: string) => void
}

function freshState(): DemoMutableState {
    return {
        anchor: Date.now(),
        handed: {},
        decisions: {},
        snoozed: {},
        closed: {},
        read: {},
        reviewers: {},
        priorities: {},
        archivedChats: {},
        log: {},
        isRefreshing: false,
    }
}

let entryCounter = 0
const hydration = createPersistHydrationGate()

function entry(tag: DemoLogTag, text: string, via?: string): DemoLogEntry {
    entryCounter += 1
    return { id: `demo-log-${entryCounter}`, tag, text, at: new Date().toISOString(), ...(via ? { via } : {}) }
}

function appendLog(
    log: DemoMutableState['log'],
    reportId: string,
    ...entries: DemoLogEntry[]
): DemoMutableState['log'] {
    return { ...log, [reportId]: [...(log[reportId] ?? []), ...entries] }
}

// Mirrors the live activity line for a dismissal artefact. "Something else…" has no label there.
function verdictSentence(verb: 'resolved' | 'dismissed', reason: ResolveReason | DismissReason): string {
    const options: readonly { value: string; label: string }[] =
        verb === 'resolved' ? RESOLVE_REASON_OPTIONS : DISMISSAL_REASON_OPTIONS
    const label = reason === 'other' ? undefined : options.find((option) => option.value === reason)?.label
    return label ? `${DEMO_USER_NAME} ${verb} the report as **${label}**` : `${DEMO_USER_NAME} ${verb} the report`
}

function reviewerSentence(uuids: string[]): string {
    const names = uuids.map((uuid) => DEMO_PEOPLE.find((person) => person.uuid === uuid)?.name ?? 'someone')
    if (names.length === 0) {
        return `${DEMO_USER_NAME} removed the assignee`
    }
    return `${DEMO_USER_NAME} changed assignee to **${names.join(', ')}**`
}

export const useDemoMode = create<DemoModeState>()(
    persist(
        (set) => ({
            enabled: DEMO_FROM_ENV,
            ...freshState(),
            setEnabled: (enabled) => set({ enabled, ...freshState() }),
            reset: () => set(freshState()),
            refresh: () => {
                set({ isRefreshing: true })
                setTimeout(() => set({ ...freshState(), isRefreshing: false }), REFRESH_MS)
            },
            handOff: (reportId) =>
                set((state) => ({
                    handed: { ...state.handed, [reportId]: new Date().toISOString() },
                    log: appendLog(
                        state.log,
                        reportId,
                        entry('handoff', `${DEMO_USER_NAME} handed off to **${DEMO_AGENT.name}**`),
                        entry('handoff', `${DEMO_AGENT.name} changed status from **Open** to **In progress**`, MCP_VIA)
                    ),
                })),
            answer: (reportId, answer) =>
                set((state) => ({
                    decisions: { ...state.decisions, [reportId]: answer },
                    log: appendLog(
                        state.log,
                        reportId,
                        entry('decision', `${DEMO_USER_NAME} chose **${answer.text}**`),
                        entry(
                            'decision',
                            `${DEMO_AGENT.name} changed status from **Waiting on you** to **In progress**`,
                            MCP_VIA
                        )
                    ),
                })),
            undoAnswer: (reportId) =>
                set((state) => {
                    const { [reportId]: _removed, ...decisions } = state.decisions
                    const kept = (state.log[reportId] ?? []).filter((item) => item.tag !== 'decision')
                    return { decisions, log: { ...state.log, [reportId]: kept } }
                }),
            snooze: (reportId, labels) =>
                set((state) => ({
                    snoozed: { ...state.snoozed, [reportId]: labels.row },
                    log: appendLog(
                        state.log,
                        reportId,
                        entry('snooze', `${DEMO_USER_NAME} snoozed until **${labels.activity}**`)
                    ),
                })),
            resolve: (reportId, reason) =>
                set((state) => ({
                    closed: { ...state.closed, [reportId]: 'resolved' },
                    log: appendLog(state.log, reportId, entry('verdict', verdictSentence('resolved', reason))),
                })),
            dismiss: (reportId, reason) =>
                set((state) => ({
                    closed: { ...state.closed, [reportId]: 'dismissed' },
                    log: appendLog(state.log, reportId, entry('verdict', verdictSentence('dismissed', reason))),
                })),
            setReviewers: (reportId, uuids) =>
                set((state) => ({
                    reviewers: { ...state.reviewers, [reportId]: uuids },
                    log: appendLog(state.log, reportId, entry('reviewers', reviewerSentence(uuids))),
                })),
            setPriority: (reportId, priority) =>
                set((state) => ({
                    priorities: { ...state.priorities, [reportId]: priority },
                    log: appendLog(
                        state.log,
                        reportId,
                        entry('priority', `${DEMO_USER_NAME} changed priority to **${priority}**`)
                    ),
                })),
            markRead: (reportId) =>
                set((state) => (state.read[reportId] ? state : { read: { ...state.read, [reportId]: true } })),
            markUnread: (reportId) =>
                set((state) =>
                    state.read[reportId] === false ? state : { read: { ...state.read, [reportId]: false } }
                ),
            archiveChat: (taskId) => set((state) => ({ archivedChats: { ...state.archivedChats, [taskId]: true } })),
            unarchiveChat: (taskId) =>
                set((state) => {
                    const { [taskId]: _removed, ...archivedChats } = state.archivedChats
                    return { archivedChats }
                }),
        }),
        {
            name: 'posthog-mobile-demo',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ enabled: state.enabled }),
            onRehydrateStorage: () => () => hydration.settle(),
        }
    )
)

/** True once the persisted `enabled` flag has loaded, so routing does not flash the sign-in screen. */
export function useDemoHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

export type DataMode = 'loading' | 'demo' | 'live'

export function useDataMode(): DataMode {
    const hydrated = useDemoHydrated()
    const enabled = useDemoMode((state) => state.enabled)
    if (!hydrated) {
        return 'loading'
    }
    return enabled ? 'demo' : 'live'
}
