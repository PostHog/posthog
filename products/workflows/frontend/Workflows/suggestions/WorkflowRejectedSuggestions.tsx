import { LemonCollapse } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { WorkflowProposalApi } from '../../generated/api.schemas'

export function WorkflowRejectedSuggestions({
    proposals,
    total,
}: {
    proposals: WorkflowProposalApi[]
    total: number
}): JSX.Element {
    return (
        <LemonCollapse
            size="small"
            panels={[
                {
                    key: 'rejected',
                    header: `Rejected (${total})`,
                    content: (
                        <div className="flex flex-col gap-3" data-attr="workflow-suggestions-rejected">
                            {total > proposals.length && (
                                <span className="text-xs text-secondary">
                                    Showing {proposals.length} of {total}.
                                </span>
                            )}
                            {proposals.map((proposal) => {
                                const rejecter = proposal.resolved_by?.first_name || proposal.resolved_by?.email
                                return (
                                    <div key={proposal.id} className="flex flex-col gap-0.5">
                                        <span className="font-semibold">{proposal.title}</span>
                                        <span className="text-xs text-secondary">
                                            Rejected{rejecter ? ` by ${rejecter}` : ''}{' '}
                                            {proposal.resolved_at && <TZLabel time={proposal.resolved_at} />}
                                        </span>
                                    </div>
                                )
                            })}
                        </div>
                    ),
                },
            ]}
        />
    )
}
