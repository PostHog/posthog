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

interface WizardRunSidebarProps {
    projectId: string
    userId: number
}

export interface wizardRunSidebarLogicValues {
    userRuns: WizardRunApi[]
    dismissedRunIds: string[]
    visibleRuns: WizardRunApi[]
}

export interface wizardRunSidebarLogicActions {
    clickState: () => { value: true }
    dismissRuns: (runIds: string[]) => { runIds: string[] }
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
    actions({ clickState: true, dismissRuns: (runIds: string[]) => ({ runIds }), syncWatchedRuns: true }),
    reducers(({ props: { projectId, userId } }) => ({
        dismissedRunIds: [
            [] as string[],
            { persist: true, storageKey: `${projectId}.${userId}.wizard_sidebar_dismissed_run_ids` },
            // Store IDs instead of a cutoff so dismissing history cannot hide a subsequently discovered run.
            { dismissRuns: (state, { runIds }) => [...new Set([...(Array.isArray(state) ? state : []), ...runIds])] },
        ],
    })),
    selectors({
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
        clickState: () => {
            posthog.capture('wizard sidebar state clicked', {
                event_source: 'wizard_ui',
                project_id: projectId,
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
