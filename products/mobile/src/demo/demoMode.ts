import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { MCP_VIA } from '@/model/agent'
import type { ActivityEvent, DecisionAnswer, ReportPriority } from '@/model/types'

import { DEMO_AGENT, DEMO_USER_NAME } from './briefings'
import { DEMO_PEOPLE } from './fixtures'

const REFRESH_MS = 450
/** Builds made with EXPO_PUBLIC_DEMO_MODE=1 start in demo mode, so a simulator or preview build needs no account. */
const DEMO_FROM_ENV = process.env.EXPO_PUBLIC_DEMO_MODE === '1'

export type DemoLogTag = 'handoff' | 'decision' | 'snooze' | 'reviewers' | 'priority'

export interface DemoLogEntry extends ActivityEvent {
    tag: DemoLogTag
}

export interface DemoMutableState {
    /** Epoch ms that fixture times are relative to. */
    anchor: number
    handed: Record<string, string>
    decisions: Record<string, DecisionAnswer>
    snoozed: Record<string, string>
    /** An explicit value overrides the fixture's read state. */
    read: Record<string, boolean>
    reviewers: Record<string, string[]>
    priorities: Record<string, ReportPriority>
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
    setReviewers: (reportId: string, uuids: string[]) => void
    setPriority: (reportId: string, priority: ReportPriority) => void
    markRead: (reportId: string) => void
    markUnread: (reportId: string) => void
}

function freshState(): DemoMutableState {
    return {
        anchor: Date.now(),
        handed: {},
        decisions: {},
        snoozed: {},
        read: {},
        reviewers: {},
        priorities: {},
        log: {},
        isRefreshing: false,
    }
}

let entryCounter = 0

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
        }),
        {
            name: 'posthog-mobile-demo',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ enabled: state.enabled }),
        }
    )
)

/** True once the persisted `enabled` flag has loaded, so routing does not flash the sign-in screen. */
export function useDemoHydrated(): boolean {
    const [hydrated, setHydrated] = useState(() => useDemoMode.persist.hasHydrated())
    useEffect(() => {
        const unsubscribe = useDemoMode.persist.onFinishHydration(() => setHydrated(true))
        setHydrated(useDemoMode.persist.hasHydrated())
        return unsubscribe
    }, [])
    return hydrated
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
