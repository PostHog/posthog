// Backs the workflow chip's switcher dropdown: the repo's workflow names, loaded lazily on first open
// so detail pages don't pay for the list until the user reaches for it.

import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'

import { engineeringAnalyticsWorkflowHealth } from '../generated/api'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import type { workflowSwitcherLogicType } from './workflowSwitcherLogicType'

export interface WorkflowSwitcherLogicProps {
    repoOwner: string
    repoName: string
    sourceId: string | null
}

export const workflowSwitcherLogic = kea<workflowSwitcherLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'workflowSwitcherLogic']),
    props({} as WorkflowSwitcherLogicProps),
    key(({ repoOwner, repoName, sourceId }) => `${repoOwner}/${repoName}:${sourceId ?? ''}`),

    connect(() => ({
        values: [engineeringAnalyticsFiltersLogic, ['dateFrom', 'dateTo', 'appliedBranch']],
    })),

    actions({
        // Fired when the dropdown opens; loads once per mount instead of on every page view.
        ensureWorkflowsLoaded: true,
    }),

    loaders(({ props, values }) => ({
        // null = never loaded, so an empty result isn't refetched on every open.
        workflowNames: [
            null as string[] | null,
            {
                loadWorkflowNames: async (): Promise<string[]> => {
                    const items = await engineeringAnalyticsWorkflowHealth(String(ApiConfig.getCurrentProjectId()), {
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        branch: values.appliedBranch || undefined,
                        source_id: props.sourceId ?? undefined,
                    })
                    // Server order (top workflows by run count) — the most active ones surface first.
                    return items
                        .filter((it) => it.repo.owner === props.repoOwner && it.repo.name === props.repoName)
                        .map((it) => it.workflow_name)
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        ensureWorkflowsLoaded: () => {
            if (values.workflowNames === null && !values.workflowNamesLoading) {
                actions.loadWorkflowNames()
            }
        },
    })),
])
