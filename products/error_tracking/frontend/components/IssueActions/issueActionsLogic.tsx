import { actions, connect, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { createCohortFormData } from 'scenes/cohorts/cohortUtils'

import { ErrorTrackingFingerprintIssueStatePhantomRow, ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { BehavioralEventType, CohortType, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import {
    PhantomStateOverrides,
    buildPhantomRowsForIssue,
    phantomFingerprintStatesLogic,
} from '../../logics/phantomFingerprintStatesLogic'
import type { issueActionsLogicType } from './issueActionsLogicType'

function assignmentOverrides(assignee: ErrorTrackingIssue['assignee']): {
    assigned_user_id: number | null
    assigned_role_id: string | null
} {
    if (!assignee) {
        return { assigned_user_id: null, assigned_role_id: null }
    }
    if (assignee.type === 'user') {
        return { assigned_user_id: typeof assignee.id === 'number' ? assignee.id : null, assigned_role_id: null }
    }
    if (assignee.type === 'role') {
        return { assigned_user_id: null, assigned_role_id: typeof assignee.id === 'string' ? assignee.id : null }
    }
    return { assigned_user_id: null, assigned_role_id: null }
}

export const issueActionsLogic = kea<issueActionsLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueActions', 'issueActionsLogic']),

    connect(() => ({
        actions: [phantomFingerprintStatesLogic, ['writePhantoms']],
    })),

    actions({
        mergeIssues: (ids: string[]) => ({ ids }),
        splitIssue: (
            id: ErrorTrackingIssue['id'],
            fingerprints: { fingerprint: string; name?: string; description?: string }[]
        ) => ({
            id,
            fingerprints,
        }),
        resolveIssues: (ids: string[]) => ({ ids }),
        suppressIssues: (ids: string[]) => ({ ids }),
        activateIssues: (ids: string[]) => ({ ids }),
        assignIssues: (ids: string[], assignee: ErrorTrackingIssue['assignee']) => ({ ids, assignee }),

        updateIssueAssignee: (id: string, assignee: ErrorTrackingIssue['assignee']) => ({ id, assignee }),
        updateIssueStatus: (id: string, status: ErrorTrackingIssue['status']) => ({ id, status }),
        updateIssueName: (id: string, name: string) => ({ id, name }),
        updateIssueDescription: (id: string, description: string) => ({ id, description }),
        createIssueCohort: (id: string, name: string, description: string) => ({ id, name, description }),

        splitIssueSuccess: (newIssueIds: string[]) => ({ newIssueIds }),
        mutationSuccess: (mutationName: string) => ({ mutationName }),
        mutationFailure: (mutationName: string, error: unknown) => ({ mutationName, error }),
        clearNeedsReload: true,
    }),

    reducers({
        needsReload: [
            false,
            {
                mutationSuccess: () => true,
                clearNeedsReload: () => false,
            },
        ],
    }),

    listeners(({ actions }) => {
        /**
         * Emit phantom rows for one or more issues AFTER a successful mutation but BEFORE the
         * mutation-success signal that triggers a reload. The `await` is load-bearing — without it,
         * `reloadData` runs before `api.errorTracking.fingerprints.list` resolves and the first
         * post-mutation query misses phantoms entirely, which is exactly the race we're closing.
         */
        async function emitPhantoms(
            entries: { issueId: string; overrides: PhantomStateOverrides; fingerprints?: string[] }[]
        ): Promise<void> {
            const built = await Promise.all(
                entries.map(({ issueId, overrides, fingerprints }) =>
                    buildPhantomRowsForIssue(issueId, overrides, fingerprints ? { fingerprints } : {})
                )
            )
            const flat: ErrorTrackingFingerprintIssueStatePhantomRow[] = built.flat()
            if (flat.length > 0) {
                actions.writePhantoms(flat)
            }
        }

        async function runMutation(
            mutationName: string,
            cb: () => Promise<void>,
            onSuccessPhantoms?: () => Promise<void>
        ): Promise<void> {
            try {
                await cb()
                if (onSuccessPhantoms) {
                    // Best-effort — if phantom prep fails we still signal success so the reload happens.
                    // Worst case is we fall back to today's stale-data behaviour for this one reload.
                    try {
                        await onSuccessPhantoms()
                    } catch {
                        // swallow
                    }
                }
                actions.mutationSuccess(mutationName)
            } catch (e: unknown) {
                actions.mutationFailure(mutationName, e)
            }
        }
        return {
            mergeIssues: async ({ ids }) => {
                const [firstId, ...otherIds] = ids
                if (firstId && otherIds.length > 0) {
                    await runMutation(
                        'mergeIssues',
                        async () => {
                            posthog.capture('error_tracking_issue_merged', { primary: firstId })
                            await api.errorTracking.mergeInto(firstId, otherIds)
                        },
                        // Redirect every fingerprint of the absorbed issues to the primary so the next
                        // list query sees them as belonging to the primary without waiting for Kafka.
                        async () =>
                            emitPhantoms(otherIds.map((id) => ({ issueId: id, overrides: { issue_id: firstId } })))
                    )
                }
            },
            splitIssue: async ({ id, fingerprints }) => {
                await runMutation('splitIssues', async () => {
                    posthog.capture('error_tracking_issue_split', { issueId: id })
                    const response = await api.errorTracking.split(id, fingerprints)
                    actions.splitIssueSuccess(response.new_issue_ids)
                })
            },
            resolveIssues: async ({ ids }) => {
                await runMutation(
                    'resolveIssues',
                    async () => {
                        posthog.capture('error_tracking_issue_bulk_resolve')
                        await api.errorTracking.bulkMarkStatus(ids, 'resolved')
                    },
                    async () =>
                        emitPhantoms(ids.map((id) => ({ issueId: id, overrides: { issue_status: 'resolved' } })))
                )
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.ResolveFirstError)
            },
            suppressIssues: async ({ ids }) => {
                await runMutation(
                    'suppressIssues',
                    async () => {
                        posthog.capture('error_tracking_issue_bulk_suppress')
                        await api.errorTracking.bulkMarkStatus(ids, 'suppressed')
                    },
                    async () =>
                        emitPhantoms(ids.map((id) => ({ issueId: id, overrides: { issue_status: 'suppressed' } })))
                )
            },
            activateIssues: async ({ ids }) => {
                await runMutation(
                    'activateIssues',
                    async () => {
                        posthog.capture('error_tracking_issue_bulk_activate')
                        await api.errorTracking.bulkMarkStatus(ids, 'active')
                    },
                    async () => emitPhantoms(ids.map((id) => ({ issueId: id, overrides: { issue_status: 'active' } })))
                )
            },
            assignIssues: async ({ ids, assignee }) => {
                const overrides = assignmentOverrides(assignee)
                await runMutation(
                    'assignIssues',
                    async () => {
                        posthog.capture('error_tracking_issue_bulk_assign')
                        await api.errorTracking.bulkAssign(ids, assignee)
                    },
                    async () => emitPhantoms(ids.map((id) => ({ issueId: id, overrides })))
                )
            },
            updateIssueAssignee: async ({ id, assignee }) => {
                const overrides = assignmentOverrides(assignee)
                await runMutation(
                    'updateIssueAssignee',
                    async () => {
                        posthog.capture('error_tracking_issue_update_assignee')
                        await api.errorTracking.assignIssue(id, assignee)
                    },
                    async () => emitPhantoms([{ issueId: id, overrides }])
                )
            },
            updateIssueStatus: async ({ id, status }) => {
                await runMutation(
                    'updateIssueStatus',
                    async () => {
                        posthog.capture('error_tracking_issue_update_status')
                        await api.errorTracking.updateIssue(id, { status })
                    },
                    async () => emitPhantoms([{ issueId: id, overrides: { issue_status: status } }])
                )
            },
            updateIssueName: async ({ id, name }) => {
                await runMutation(
                    'updateIssueName',
                    async () => {
                        posthog.capture('error_tracking_issue_update_name')
                        await api.errorTracking.updateIssue(id, { name })
                    },
                    async () => emitPhantoms([{ issueId: id, overrides: { issue_name: name } }])
                )
            },
            updateIssueDescription: async ({ id, description }) => {
                await runMutation(
                    'updateIssueDescription',
                    async () => {
                        posthog.capture('error_tracking_issue_update_description')
                        await api.errorTracking.updateIssue(id, { description })
                    },
                    async () => emitPhantoms([{ issueId: id, overrides: { issue_description: description } }])
                )
            },
            createIssueCohort: async ({ id, name, description }) => {
                await runMutation('createIssueCohort', async () => {
                    let cohortParams = createCohortParams(name, description, id)
                    let formData = createCohortFormData(cohortParams)
                    let cohort = await api.cohorts.create(formData as Partial<CohortType>)
                    posthog.capture('error_tracking_issue_create_cohort', {
                        issueId: id,
                        cohortId: cohort.id,
                    })
                    await api.errorTracking.assignCohort(id, cohort.id)
                })
            },
        }
    }),
])

function createCohortParams(name: string, description: string, issueId: string): CohortType {
    return {
        id: 'new',
        name,
        description,
        groups: [],
        filters: {
            properties: {
                type: FilterLogicalOperator.Or,
                values: [
                    {
                        type: FilterLogicalOperator.Or,
                        values: [
                            {
                                key: '$exception',
                                type: BehavioralFilterKey.Behavioral,
                                value: BehavioralEventType.PerformEvent,
                                negation: false,
                                event_type: TaxonomicFilterGroupType.Events,
                                event_filters: [
                                    {
                                        key: '$exception_issue_id',
                                        type: PropertyFilterType.Event,
                                        value: [issueId],
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                                explicit_datetime: '-30d',
                            },
                        ],
                    },
                ],
            },
        },
    }
}
