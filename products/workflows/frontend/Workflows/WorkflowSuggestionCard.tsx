import { useActions, useValues } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { WorkflowProposalApi, WorkflowProposalSourceTypeEnumApi } from '../generated/api.schemas'
import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'
import { WorkflowSuggestionDetails } from './WorkflowSuggestionDetails'
import { WorkflowSuggestionEvidence } from './WorkflowSuggestionEvidence'

const SOURCE_LABELS: Record<WorkflowProposalSourceTypeEnumApi, string> = {
    scout: 'Suggested by a scout',
    responder: 'Suggested by a responder',
    human: 'Suggested by a person',
    stub: 'Suggested by a stub generator',
}

export function WorkflowSuggestionCard({ id, proposal }: { id: string; proposal: WorkflowProposalApi }): JSX.Element {
    const { resolvingId, resolvingAction } = useValues(workflowProposalsLogic({ id }))
    const { approveProposal, rejectProposal } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

    const busyElsewhere = resolvingId !== null && resolvingId !== proposal.id

    return (
        <div className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
            <div className="flex items-start gap-2">
                <IconBolt className="text-lg shrink-0 mt-0.5" />
                <div className="flex flex-col gap-1 grow">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold">{proposal.title}</span>
                        <LemonTag type="highlight">{SOURCE_LABELS[proposal.source_type]}</LemonTag>
                        {proposal.is_stale && (
                            <Tooltip title="The live workflow has changed since this was suggested. Check it still makes sense before you publish.">
                                <LemonTag type="warning">Out of date</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    <p className="mb-0 text-secondary">{proposal.rationale}</p>
                    <WorkflowSuggestionEvidence evidence={proposal.evidence} />
                    <span className="text-xs text-secondary">
                        Suggested <TZLabel time={proposal.created_at} /> against version {proposal.base_version}
                    </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Workflow}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={workflowUserAccessLevel ?? undefined}
                    >
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="workflow-suggestion-reject"
                            onClick={() => rejectProposal(proposal.id)}
                            loading={resolvingId === proposal.id && resolvingAction === 'reject'}
                            disabledReason={busyElsewhere ? 'Another suggestion is being resolved' : undefined}
                        >
                            Reject
                        </LemonButton>
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Workflow}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={workflowUserAccessLevel ?? undefined}
                    >
                        <LemonButton
                            type="primary"
                            size="small"
                            data-attr="workflow-suggestion-approve"
                            onClick={() => approveProposal(proposal.id)}
                            loading={resolvingId === proposal.id && resolvingAction === 'approve'}
                            disabledReason={busyElsewhere ? 'Another suggestion is being resolved' : undefined}
                        >
                            Approve as draft
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'details',
                        header: 'What it changes and why',
                        content: <WorkflowSuggestionDetails proposal={proposal} />,
                    },
                ]}
            />
        </div>
    )
}
