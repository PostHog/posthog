import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonModal, LemonSkeleton, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'

import { MarkdownTextDiff } from 'lib/components/MarkdownNotebook/MarkdownTextDiff'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ContentAutopilotBriefPanel } from './ContentAutopilotBriefPanel'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSourceLedger } from './ContentAutopilotSourceLedger'
import { ContentAutopilotValidationSummary } from './ContentAutopilotValidationSummary'

export const ContentAutopilotProposalDetail = (): JSX.Element | null => {
    const {
        selectedProposal,
        selectedProposalId,
        proposedMarkdown,
        proposalHasUnsavedChanges,
        proposalMutationLoading,
        exportedProposalLoading,
        proposalActionReasons,
        proposalTab,
    } = useValues(contentAutopilotLogic)
    const {
        selectProposal,
        setProposedMarkdown,
        saveProposal,
        rejectProposal,
        regenerateProposal,
        exportProposal,
        setProposalTab,
    } = useActions(contentAutopilotLogic)

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
            <LemonModal isOpen onClose={closeProposal} title="Loading draft" width={960}>
                <LemonSkeleton className="h-72 w-full" />
            </LemonModal>
        )
    }

    const confirmReject = (): void => {
        LemonDialog.open({
            title: 'Reject this draft?',
            description: 'The draft leaves the review queue. This does not change your site.',
            primaryButton: {
                children: 'Reject draft',
                status: 'danger',
                onClick: () => rejectProposal(selectedProposal.id),
            },
            secondaryButton: { children: 'Keep draft' },
        })
    }

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
                            disabledReason={proposalActionReasons.reject}
                        >
                            Reject
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={() => regenerateProposal(selectedProposal.id)}
                            loading={proposalMutationLoading}
                            disabledReason={proposalActionReasons.regenerate}
                        >
                            Regenerate
                        </LemonButton>
                    </div>
                    <div className="flex gap-2">
                        <LemonButton
                            type="primary"
                            onClick={() => exportProposal(selectedProposal.id)}
                            loading={exportedProposalLoading}
                            disabledReason={proposalActionReasons.exportMarkdown}
                            data-attr="content-autopilot-download-draft"
                        >
                            Download Markdown
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <ContentAutopilotValidationSummary report={selectedProposal.validation_report} />

                <LemonTabs
                    activeKey={proposalTab}
                    onChange={setProposalTab}
                    data-attr="content-autopilot-proposal-tabs"
                    rightSlot={
                        proposalTab === 'draft' ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => saveProposal(selectedProposal.id)}
                                loading={proposalMutationLoading}
                                disabledReason={proposalActionReasons.save}
                            >
                                Save changes
                            </LemonButton>
                        ) : null
                    }
                    tabs={[
                        {
                            key: 'preview',
                            label: 'Preview',
                            content: proposedMarkdown ? (
                                <div className="max-h-160 overflow-auto rounded border p-4">
                                    <LemonMarkdown disableImages="all" disableLinks disableMentions>
                                        {proposedMarkdown}
                                    </LemonMarkdown>
                                </div>
                            ) : (
                                <p className="text-muted m-0">Nothing to preview yet. Regenerate to write the draft.</p>
                            ),
                        },
                        {
                            key: 'draft',
                            label: 'Edit',
                            content: (
                                <LemonTextArea
                                    aria-label="Draft Markdown"
                                    value={proposedMarkdown}
                                    onChange={setProposedMarkdown}
                                    minRows={18}
                                    className="font-mono"
                                />
                            ),
                        },
                        selectedProposal.proposal_type === 'page_improvement' && selectedProposal.original_markdown
                            ? {
                                  key: 'changes',
                                  label: 'Changes',
                                  content: (
                                      <div className="max-h-160 overflow-auto rounded border p-3 whitespace-pre-wrap font-mono text-sm">
                                          <MarkdownTextDiff
                                              before={selectedProposal.original_markdown}
                                              after={proposedMarkdown}
                                          />
                                      </div>
                                  ),
                              }
                            : null,
                        {
                            key: 'brief',
                            label: 'Brief',
                            content: (
                                <ContentAutopilotBriefPanel
                                    brief={selectedProposal.brief}
                                    evidence={selectedProposal.evidence}
                                />
                            ),
                        },
                        {
                            key: 'sources',
                            label: 'Sources',
                            content: (
                                <ContentAutopilotSourceLedger
                                    entries={selectedProposal.source_ledger}
                                    notes={selectedProposal.content_package.source_notes}
                                />
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
