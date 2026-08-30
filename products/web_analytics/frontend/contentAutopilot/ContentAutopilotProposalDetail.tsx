import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonModal,
    LemonSkeleton,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'

export const ContentAutopilotProposalDetail = (): JSX.Element | null => {
    const {
        selectedProposal,
        selectedProposalId,
        proposedMarkdown,
        proposalDetailLoading,
        proposalHasUnsavedChanges,
        proposalMutationLoading,
        exportedProposalLoading,
    } = useValues(contentAutopilotLogic)
    const { selectProposal, setProposedMarkdown, saveProposal, rejectProposal, regenerateProposal, exportProposal } =
        useActions(contentAutopilotLogic)

    if (!selectedProposalId) {
        return null
    }

    const closeProposal = (): void => {
        if (proposalHasUnsavedChanges) {
            LemonDialog.open({
                title: 'Discard unsaved changes?',
                description: 'Your Markdown changes have not been saved.',
                primaryButton: {
                    children: 'Discard changes',
                    status: 'danger',
                    onClick: () => selectProposal(null),
                },
                secondaryButton: { children: 'Keep editing' },
            })
            return
        }
        selectProposal(null)
    }

    if (!selectedProposal) {
        return (
            <LemonModal isOpen onClose={closeProposal} title="Loading proposal" width={960}>
                <LemonSkeleton className="h-72 w-full" />
            </LemonModal>
        )
    }

    const confirmReject = (): void => {
        LemonDialog.open({
            title: 'Reject this proposal?',
            description: 'The proposal will leave the review queue. This does not change your site or repository.',
            primaryButton: {
                children: 'Reject proposal',
                status: 'danger',
                onClick: () => rejectProposal(selectedProposal.id),
            },
            secondaryButton: { children: 'Keep proposal' },
        })
    }

    const deliveryBlocked = !selectedProposal.validation_report.passed
        ? 'Resolve blocking validation failures before delivery'
        : selectedProposal.lifecycle_status !== 'ready_for_review'
          ? 'Only proposals ready for review can be delivered'
          : undefined
    const deliveryMutationLoading = exportedProposalLoading
    const deliveryDisabledReason =
        deliveryBlocked ??
        (proposalHasUnsavedChanges ? 'Save or discard your changes before delivery' : undefined) ??
        (proposalMutationLoading ? 'Wait for proposal changes to finish' : undefined)
    const reviewDisabledReason = deliveryMutationLoading
        ? 'Wait for delivery to finish'
        : proposalHasUnsavedChanges
          ? 'Save or discard your changes first'
          : undefined

    return (
        <LemonModal
            isOpen
            onClose={closeProposal}
            title={selectedProposal.title}
            description={selectedProposal.target_query || selectedProposal.target_url}
            width={960}
            footer={
                <div className="flex flex-wrap gap-2 justify-between w-full">
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={confirmReject}
                            loading={proposalMutationLoading}
                            disabledReason={reviewDisabledReason}
                        >
                            Reject
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={() => regenerateProposal(selectedProposal.id)}
                            loading={proposalMutationLoading}
                            disabledReason={reviewDisabledReason}
                        >
                            Regenerate
                        </LemonButton>
                    </div>
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => exportProposal(selectedProposal.id)}
                            loading={exportedProposalLoading}
                            disabledReason={deliveryDisabledReason}
                        >
                            Export Markdown
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex flex-col gap-5">
                {selectedProposal.evidence.length > 0 ? (
                    <section>
                        <h3>Why PostHog selected this</h3>
                        <div className="flex flex-col gap-2">
                            {selectedProposal.evidence.map((evidence) => (
                                <div
                                    key={`${evidence.opportunity_kind}-${evidence.page_url}-${evidence.query}-${evidence.explanation}`}
                                    className="rounded border p-3"
                                >
                                    <LemonTag>{evidence.opportunity_kind.replaceAll('_', ' ')}</LemonTag>
                                    <p className="mb-0 mt-2">{evidence.explanation}</p>
                                    {evidence.query ? (
                                        <div className="text-sm mt-2">Query: {evidence.query}</div>
                                    ) : null}
                                </div>
                            ))}
                        </div>
                    </section>
                ) : null}

                <section>
                    <h3>Validation</h3>
                    {!selectedProposal.validation_report.passed ? (
                        <LemonBanner type="error" className="mb-3">
                            This proposal has blocking failures and cannot be delivered.
                        </LemonBanner>
                    ) : null}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {selectedProposal.validation_report.checks.map((check) => (
                            <div key={check.check_key} className="rounded border p-3">
                                <div className="flex items-center justify-between gap-2">
                                    <span className="font-semibold">{check.label}</span>
                                    <LemonTag type={check.passed ? 'success' : check.blocking ? 'danger' : 'warning'}>
                                        {check.passed ? 'Passed' : check.blocking ? 'Blocked' : 'Review'}
                                    </LemonTag>
                                </div>
                                <div className="text-sm mt-1 text-muted">{check.message}</div>
                            </div>
                        ))}
                    </div>
                </section>

                <section>
                    <div className="flex items-center justify-between gap-2 mb-2">
                        <h3 className="m-0">Draft</h3>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => saveProposal(selectedProposal.id)}
                            loading={proposalMutationLoading}
                            disabledReason={
                                proposalDetailLoading
                                    ? 'Wait for the proposal to load'
                                    : deliveryMutationLoading
                                      ? 'Wait for delivery to finish'
                                      : !proposalHasUnsavedChanges
                                        ? 'No unsaved changes'
                                        : undefined
                            }
                        >
                            Save changes
                        </LemonButton>
                    </div>
                    {selectedProposal.proposal_type === 'page_improvement' && selectedProposal.original_markdown ? (
                        <LemonCollapse
                            className="mb-3"
                            panels={[
                                {
                                    key: 'original',
                                    header: 'View original content',
                                    content: (
                                        <pre className="max-h-72 overflow-auto rounded border p-3 whitespace-pre-wrap">
                                            {selectedProposal.original_markdown}
                                        </pre>
                                    ),
                                },
                            ]}
                        />
                    ) : null}
                    <LemonTextArea
                        aria-label="Proposal Markdown"
                        value={proposedMarkdown}
                        onChange={setProposedMarkdown}
                        minRows={18}
                        className="font-mono"
                    />
                </section>
            </div>
        </LemonModal>
    )
}
