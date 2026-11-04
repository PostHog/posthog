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

import type { WizardRunApi } from '../../generated/api.schemas'
import { wizardRunIsActive } from '../../lib/wizardRunDisplay'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'

// pinned: analytics property values, renaming breaks dashboards
export type WizardRunStateLocation = 'navbar_sidebar' | 'today_more_menu'

interface WizardRunSidebarProps {
    projectId: string
    userId: number
}

export interface wizardRunSidebarLogicValues {
    userRuns: WizardRunApi[]
    dismissedRunIds: string[]
    visibleRuns: WizardRunApi[]
    runsSeenAt: string | null
    hasUnseenRuns: boolean
}

export interface wizardRunSidebarLogicActions {
    clickState: (location: WizardRunStateLocation) => { location: WizardRunStateLocation }
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
        values: [wizardRunSyncLogic({ projectId }), ['userRuns']],
        actions: [wizardRunSyncLogic({ projectId }), ['watchRuns']],
    })),
    actions({
        clickState: (location: WizardRunStateLocation) => ({ location }),
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
        hasUnseenRuns: [
            (s) => [s.userRuns, s.runsSeenAt],
            (runs: WizardRunApi[], seenAt: string | null): boolean =>
                runs.some((run) => seenAt === null || (run.finished_at ?? run.created_at) > seenAt),
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
    listeners(({ actions, values, props: { projectId } }) => ({
        [wizardRunSyncLogic({ projectId }).actionTypes.runsLoaded]: () => actions.syncWatchedRuns(),
        [wizardRunSyncLogic({ projectId }).actionTypes.runUpdated]: () => actions.syncWatchedRuns(),
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
