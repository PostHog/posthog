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

import type { WizardDetectedWarehouseSourceApi, WizardRunApi } from '../../generated/api.schemas'
import { wizardRunIsActive } from '../../lib/wizardRunDisplay'
import { wizardDetectedSourcesLogic } from '../../logics/wizardDetectedSourcesLogic'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'

export type WizardRailState = 'idle' | 'running' | 'completed' | 'failed'

// pinned: analytics property values, renaming breaks dashboards
export type WizardRunStateLocation = 'navbar_sidebar' | 'today_rail'

// A cloud run reports its codebase scan shortly after it starts, so the sources show up while it runs.
const DETECTED_SOURCES_REFRESH_MS = 30_000

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
    runDetectedSources: WizardDetectedWarehouseSourceApi[]
    railState: WizardRailState
}

export interface wizardRunSidebarLogicActions {
    clickState: (location: WizardRunStateLocation) => { location: WizardRunStateLocation }
    clickDetectedSource: (sourceType: string) => { sourceType: string }
    loadDetectedSources: () => void
    refreshDetectedSources: () => { value: true }
    dismissRuns: (runIds: string[]) => { runIds: string[] }
    markRunsSeen: () => { seenAt: string }
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
        values: [wizardRunSyncLogic({ projectId }), ['userRuns'], wizardDetectedSourcesLogic, ['detectedSources']],
        actions: [
            wizardRunSyncLogic({ projectId }),
            ['watchRuns'],
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
    })),
    selectors({
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
    listeners(({ actions, values, cache, props: { projectId } }) => ({
        [wizardRunSyncLogic({ projectId }).actionTypes.runsLoaded]: () => {
            actions.syncWatchedRuns()
            actions.refreshDetectedSources()
        },
        [wizardRunSyncLogic({ projectId }).actionTypes.runUpdated]: () => {
            actions.syncWatchedRuns()
            actions.refreshDetectedSources()
        },
        refreshDetectedSources: () => {
            const now = Date.now()
            if (
                !values.visibleRuns.some(wizardRunIsActive) ||
                now - (cache.detectedSourcesLoadedAt ?? 0) < DETECTED_SOURCES_REFRESH_MS
            ) {
                return
            }
            cache.detectedSourcesLoadedAt = now
            actions.loadDetectedSources()
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
    })),
    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            actions.syncWatchedRuns()
            return () => actions.watchRuns('sidebar', [])
        }, 'sidebar-run-watch')
    }),
])
