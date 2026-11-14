import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import type {
    WizardDetectedWarehouseSourceApi,
    WizardRunApi,
    WizardRunArtifactApi,
    WizardRunTaskApi,
} from '../../generated/api.schemas'
import { wizardRunIsActive, wizardRunProgressFraction } from '../../lib/wizardRunDisplay'
import { wizardDetectedSourcesLogic } from '../../logics/wizardDetectedSourcesLogic'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'

export type WizardRailState = 'idle' | 'running' | 'completed' | 'failed'

// pinned: analytics property values, renaming breaks dashboards
export type WizardRunStateLocation = 'navbar_sidebar' | 'today_rail'

const DETECTED_SOURCES_REFRESH_MS = 30_000
const RAIL_RECENT_RUN_WINDOW_MS = 24 * 60 * 60 * 1000

function pullRequestMerged(artifacts: WizardRunArtifactApi[]): boolean {
    return artifacts.some((artifact) => artifact.artifact_type === 'pull_request' && artifact.state === 'merged')
}

function finishedSince(run: WizardRunApi, cutoff: number): boolean {
    return !!run.finished_at && Date.parse(run.finished_at) >= cutoff
}

interface WizardRunSidebarProps {
    projectId: string
    userId: number
}

export interface wizardRunSidebarLogicValues {
    userRuns: WizardRunApi[]
    dismissedRunIds: string[]
    visibleRuns: WizardRunApi[]
    runsSeenAt: string | null
    detectedSources: WizardDetectedWarehouseSourceApi[] | null
    detectedSourcesLoading: boolean
    runDetectedSources: WizardDetectedWarehouseSourceApi[]
    railEligible: boolean
    runsAwaitingArtifacts: WizardRunApi[]
    railVisible: boolean
    railState: WizardRailState
    railProgress: number
    tasksByRunId: Record<string, readonly WizardRunTaskApi[]>
    artifactsByRunId: Record<string, WizardRunArtifactApi[]>
    runDataErrors: Record<string, string | null>
}

export interface wizardRunSidebarLogicActions {
    clickState: (location: WizardRunStateLocation) => { location: WizardRunStateLocation }
    clickDetectedSource: (sourceType: string) => { sourceType: string }
    loadDetectedSources: () => void
    loadRunData: (run: WizardRunApi) => { run: WizardRunApi }
    refreshDetectedSources: () => { value: true }
    dismissRuns: (runIds: string[]) => { runIds: string[] }
    markRunsSeen: () => { seenAt: string }
    revealRail: () => { value: true }
    syncWatchedRuns: () => { value: true }
    watchRuns: (source: string, runIds: string[]) => { source: string; runIds: string[] }
}

export type wizardRunSidebarLogicType = MakeLogicType<
    wizardRunSidebarLogicValues,
    wizardRunSidebarLogicActions,
    WizardRunSidebarProps
>

export const wizardRunSidebarLogic: LogicWrapper<wizardRunSidebarLogicType> = kea<wizardRunSidebarLogicType>([
    props({} as WizardRunSidebarProps),
    key(({ projectId, userId }) => `${projectId}.${userId}`),
    path((key) => ['products', 'wizard', 'wizardRunSidebarLogic', key]),
    connect(({ projectId }: WizardRunSidebarProps) => ({
        values: [
            wizardRunSyncLogic({ projectId }),
            ['userRuns', 'tasksByRunId', 'artifactsByRunId', 'runDataErrors'],
            wizardDetectedSourcesLogic,
            ['detectedSources', 'detectedSourcesLoading'],
        ],
        actions: [
            wizardRunSyncLogic({ projectId }),
            ['watchRuns', 'loadRunData'],
            wizardDetectedSourcesLogic,
            ['loadDetectedSources'],
        ],
    })),
    actions({
        clickState: (location: WizardRunStateLocation) => ({ location }),
        clickDetectedSource: (sourceType: string) => ({ sourceType }),
        refreshDetectedSources: true,
        dismissRuns: (runIds: string[]) => ({ runIds }),
        markRunsSeen: () => ({ seenAt: new Date().toISOString() }),
        syncWatchedRuns: true,
        revealRail: true,
    }),
    reducers(({ props: { projectId, userId } }) => ({
        dismissedRunIds: [
            [] as string[],
            { persist: true, storageKey: `${projectId}.${userId}.wizard_sidebar_dismissed_run_ids` },
            // Store IDs instead of a cutoff so dismissing history cannot hide a subsequently discovered run.
            { dismissRuns: (state, { runIds }) => [...new Set([...(Array.isArray(state) ? state : []), ...runIds])] },
        ],
        runsSeenAt: [
            null as string | null,
            { persist: true, storageKey: `${projectId}.${userId}.wizard_runs_seen_at` },
            { markRunsSeen: (_, { seenAt }) => seenAt },
        ],
        // Only a reload resets this, so dismissing runs or the 24-hour window ending never removes the tile mid-session.
        railVisible: [false, { revealRail: () => true }],
    })),
    selectors({
        // A finished run whose pull request merged is done with. Its leftover sources move to "For you today".
        railEligible: [
            (s) => [s.visibleRuns, s.artifactsByRunId, s.runDataErrors],
            (
                runs: WizardRunApi[],
                artifactsByRunId: Record<string, WizardRunArtifactApi[]>,
                runDataErrors: Record<string, string | null>
            ): boolean => {
                const cutoff = Date.now() - RAIL_RECENT_RUN_WINDOW_MS
                return runs.some((run) => {
                    if (wizardRunIsActive(run)) {
                        return true
                    }
                    if (!finishedSince(run, cutoff)) {
                        return false
                    }
                    const artifacts = artifactsByRunId[run.id]
                    return artifacts ? !pullRequestMerged(artifacts) : !!runDataErrors[run.id]
                })
            },
        ],
        runsAwaitingArtifacts: [
            (s) => [s.visibleRuns, s.artifactsByRunId, s.runDataErrors],
            (
                runs: WizardRunApi[],
                artifactsByRunId: Record<string, WizardRunArtifactApi[]>,
                runDataErrors: Record<string, string | null>
            ): WizardRunApi[] => {
                const cutoff = Date.now() - RAIL_RECENT_RUN_WINDOW_MS
                return runs.filter(
                    (run) =>
                        !wizardRunIsActive(run) &&
                        finishedSince(run, cutoff) &&
                        !artifactsByRunId[run.id] &&
                        !runDataErrors[run.id]
                )
            },
        ],
        railState: [
            (s) => [s.visibleRuns, s.runsSeenAt],
            (runs: WizardRunApi[], seenAt: string | null): WizardRailState => {
                if (runs.some(wizardRunIsActive)) {
                    return 'running'
                }
                const latestUnseen = runs
                    .filter((run) => run.finished_at && (seenAt === null || run.finished_at > seenAt))
                    .sort((a, b) => (b.finished_at ?? '').localeCompare(a.finished_at ?? ''))[0]
                if (latestUnseen?.status === 'failed') {
                    return 'failed'
                }
                return latestUnseen?.status === 'completed' ? 'completed' : 'idle'
            },
        ],
        railProgress: [
            (s) => [s.visibleRuns, s.tasksByRunId],
            (runs: WizardRunApi[], tasksByRunId: Record<string, readonly WizardRunTaskApi[]>): number => {
                const activeRun = runs.find(wizardRunIsActive)
                return activeRun ? wizardRunProgressFraction(activeRun, tasksByRunId[activeRun.id] ?? []) : 0
            },
        ],
        runDetectedSources: [
            (s) => [s.detectedSources, s.visibleRuns],
            (
                sources: WizardDetectedWarehouseSourceApi[] | null,
                runs: WizardRunApi[]
            ): WizardDetectedWarehouseSourceApi[] => {
                if (!sources || runs.length === 0) {
                    return []
                }
                const earliestRun = runs.reduce(
                    (earliest, run) => (run.created_at < earliest ? run.created_at : earliest),
                    runs[0].created_at
                )
                return sources.filter((source) => source.last_seen_at >= earliestRun)
            },
        ],
        visibleRuns: [
            (s) => [s.userRuns, s.dismissedRunIds],
            (runs: WizardRunApi[], dismissed: string[]): WizardRunApi[] => {
                const dismissedIds = new Set(Array.isArray(dismissed) ? dismissed : [])
                return runs
                    .filter((run) => !dismissedIds.has(run.id))
                    .sort((a, b) => Number(wizardRunIsActive(b)) - Number(wizardRunIsActive(a)))
            },
        ],
    }),
    listeners(({ actions, values, cache, props: { projectId } }) => {
        const revealIfEligible = (): void => {
            if (!values.railVisible && values.railEligible) {
                actions.revealRail()
            }
        }
        return {
            [wizardRunSyncLogic({ projectId }).actionTypes.runsLoaded]: () => {
                actions.syncWatchedRuns()
                values.runsAwaitingArtifacts.forEach((run) => actions.loadRunData(run))
                revealIfEligible()
            },
            [wizardRunSyncLogic({ projectId }).actionTypes.runDataLoaded]: revealIfEligible,
            [wizardRunSyncLogic({ projectId }).actionTypes.runDataFailed]: revealIfEligible,
            [wizardRunSyncLogic({ projectId }).actionTypes.runUpdated]: () => actions.syncWatchedRuns(),
            // Runs on a fixed cadence, never per streamed update. A run's scan can land any time until it ends,
            // so every run seen active is refreshed until a load requested after it ended succeeds.
            refreshDetectedSources: () => {
                if (values.detectedSourcesLoading) {
                    return
                }
                const pending: Set<string> = (cache.runsAwaitingSources ??= new Set<string>())
                const activeRunIds = values.visibleRuns.filter(wizardRunIsActive).map((run) => run.id)
                activeRunIds.forEach((id) => pending.add(id))
                if (pending.size === 0) {
                    return
                }
                cache.finishedAtRequest = [...pending].filter((id) => !activeRunIds.includes(id))
                actions.loadDetectedSources()
            },
            [wizardDetectedSourcesLogic.actionTypes.loadDetectedSourcesSuccess]: () => {
                for (const id of cache.finishedAtRequest ?? []) {
                    cache.runsAwaitingSources?.delete(id)
                }
            },
            clickDetectedSource: ({ sourceType }) => {
                posthog.capture('wizard detected source clicked', {
                    event_source: 'wizard_ui',
                    project_id: projectId,
                    source_type: sourceType,
                    detected_source_count: values.runDetectedSources.length,
                })
            },
            syncWatchedRuns: () =>
                actions.watchRuns(
                    'sidebar',
                    values.visibleRuns.map((run) => run.id)
                ),
            clickState: ({ location }) => {
                posthog.capture('wizard sidebar state clicked', {
                    event_source: 'wizard_ui',
                    project_id: projectId,
                    location,
                    run_count: values.visibleRuns.length,
                    active_run_count: values.visibleRuns.filter(wizardRunIsActive).length,
                })
            },
            dismissRuns: ({ runIds }) => {
                actions.syncWatchedRuns()
                posthog.capture('wizard sidebar state dismissed', {
                    event_source: 'wizard_ui',
                    project_id: projectId,
                    run_count: runIds.length,
                    remaining_run_count: values.visibleRuns.length,
                })
            },
        }
    }),
    afterMount(({ actions, values, cache }) => {
        if (values.railEligible) {
            actions.revealRail()
        }
        cache.disposables.add(() => {
            actions.syncWatchedRuns()
            return () => actions.watchRuns('sidebar', [])
        }, 'sidebar-run-watch')
        cache.disposables.add(() => {
            const interval = setInterval(() => actions.refreshDetectedSources(), DETECTED_SOURCES_REFRESH_MS)
            return () => clearInterval(interval)
        }, 'detected-sources-refresh')
    }),
])
