import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { WorkflowProposalApi } from '../generated/api.schemas'
import { workflowLogic } from './workflowLogic'

export function WorkflowStagedSuggestion({ id, proposal }: { id: string; proposal: WorkflowProposalApi }): JSX.Element {
    const { draftActionPending, publishDisabledReason, workflowUserAccessLevel } = useValues(workflowLogic({ id }))
    const { publishDraft } = useActions(workflowLogic({ id }))
    const approver = proposal.resolved_by?.first_name || proposal.resolved_by?.email
    return (
        <div className="border rounded p-3 bg-surface-primary flex items-center gap-3 flex-wrap">
            <div className="flex flex-col gap-1 grow">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold">{proposal.title}</span>
                    <LemonTag type="highlight">Staged as draft</LemonTag>
                </div>
                <span className="text-xs text-secondary">
                    Approved{approver ? ` by ${approver}` : ''}{' '}
                    {proposal.resolved_at && <TZLabel time={proposal.resolved_at} />}. It is the workflow's draft now;
                    publish the draft to make it live.
                </span>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                data-attr="workflow-suggestion-open-draft"
                onClick={() => router.actions.push(urls.workflow(id, 'workflow'))}
            >
                Open draft
            </LemonButton>
            <AccessControlAction
                resourceType={AccessControlResourceType.Workflow}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={workflowUserAccessLevel ?? undefined}
            >
                {({ disabledReason }) => (
                    <LemonButton
                        type="primary"
                        size="small"
                        data-attr="workflow-suggestion-publish"
                        loading={draftActionPending === 'publish'}
                        disabledReason={disabledReason ?? publishDisabledReason}
                        // The same publish the header runs, preview and confirm included.
                        onClick={() => publishDraft()}
                    >
                        Publish
                    </LemonButton>
                )}
            </AccessControlAction>
        </div>
    )
}
