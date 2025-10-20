import { actions, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import type { issueActionsLogicType } from './issueActionsLogicType'

export const issueActionsLogic = kea<issueActionsLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueActions', 'issueActionsLogic']),

    actions({
        mergeIssues: (ids: string[]) => ({ ids }),
        splitIssue: (id: ErrorTrackingIssue['id'], fingerprints: string[], exclusive: boolean = true) => ({
            id,
            fingerprints,
            exclusive,
        }),
        resolveIssues: (ids: string[]) => ({ ids }),
        suppressIssues: (ids: string[]) => ({ ids }),
        activateIssues: (ids: string[]) => ({ ids }),
        assignIssues: (ids: string[], assignee: ErrorTrackingIssue['assignee']) => ({ ids, assignee }),

        updateIssueAssignee: (id: string, assignee: ErrorTrackingIssue['assignee']) => ({ id, assignee }),
        updateIssueStatus: (id: string, status: ErrorTrackingIssue['status']) => ({ id, status }),
        updateIssueName: (id: string, name: string) => ({ id, name }),
        updateIssueDescription: (id: string, description: string) => ({ id, description }),

        mutationSuccess: (mutationName: string) => ({ mutationName }),
        mutationFailure: (mutationName: string, error: unknown) => ({ mutationName, error }),
    }),

    listeners(({ actions }) => {
        async function runMutation(mutationName: string, cb: () => Promise<void>): Promise<void> {
            try {
                await cb()
                actions.mutationSuccess(mutationName)
            } catch (e: unknown) {
                actions.mutationFailure(mutationName, e)
            }
        }
        return {
            mergeIssues: async ({ ids }) => {
                const [firstId, ...otherIds] = ids
                if (firstId && otherIds.length > 0) {
                    await runMutation('mergeIssues', async () => {
                        posthog.capture('error_tracking_issue_merged', { primary: firstId })
                        await api.errorTracking.mergeInto(firstId, otherIds)
                    })
                }
            },
            splitIssue: async ({ id, fingerprints, exclusive }) => {
                await runMutation('splitIssues', async () => {
                    posthog.capture('error_tracking_issue_split', { issueId: id })
                    await api.errorTracking.split(id, fingerprints, exclusive)
                })
            },
            resolveIssues: async ({ ids }) => {
                await runMutation('resolveIssues', async () => {
                    posthog.capture('error_tracking_issue_bulk_resolve')
                    await api.errorTracking.bulkMarkStatus(ids, 'resolved')
                })
            },
            suppressIssues: async ({ ids }) => {
                await runMutation('suppressIssues', async () => {
                    posthog.capture('error_tracking_issue_bulk_suppress')
                    await api.errorTracking.bulkMarkStatus(ids, 'suppressed')
                })
            },
            activateIssues: async ({ ids }) => {
                await runMutation('activateIssues', async () => {
                    posthog.capture('error_tracking_issue_bulk_activate')
                    await api.errorTracking.bulkMarkStatus(ids, 'active')
                })
            },
            assignIssues: async ({ ids, assignee }) => {
                await runMutation('assignIssues', async () => {
                    posthog.capture('error_tracking_issue_bulk_assign')
                    await api.errorTracking.bulkAssign(ids, assignee)
                })
            },
            updateIssueAssignee: async ({ id, assignee }) => {
                await runMutation('updateIssueAssignee', async () => {
                    posthog.capture('error_tracking_issue_update_assignee')
                    await api.errorTracking.assignIssue(id, assignee)
                })
            },
            updateIssueStatus: async ({ id, status }) => {
                await runMutation('updateIssueStatus', async () => {
                    posthog.capture('error_tracking_issue_update_status')
                    await api.errorTracking.updateIssue(id, { status })
                })
            },
            updateIssueName: async ({ id, name }) => {
                await runMutation('updateIssueName', async () => {
                    posthog.capture('error_tracking_issue_update_name')
                    await api.errorTracking.updateIssue(id, { name })
                })
            },
            updateIssueDescription: async ({ id, description }) => {
                await runMutation('updateIssueDescription', async () => {
                    posthog.capture('error_tracking_issue_update_description')
                    await api.errorTracking.updateIssue(id, { description })
                })
            },
        }
    }),
])
