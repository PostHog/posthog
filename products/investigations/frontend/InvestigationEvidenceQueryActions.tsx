import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { InvestigationDocument, InvestigationEvidence } from './investigationDocument'
import { InvestigationQueryTask } from './queryAssistantHelpers'

export function InvestigationEvidenceQueryActions({
    document,
    selected,
    onAskAI,
}: {
    document: InvestigationDocument
    selected: InvestigationEvidence
    onAskAI?: (task: InvestigationQueryTask, evidenceId: string) => void
}): JSX.Element {
    const latestResult = document.runs.at(-1)?.results.find((result) => result.evidenceId === selected.id)
    const queryError = latestResult?.sql === selected.sql ? latestResult?.error : null
    return (
        <>
            {' '}
            {queryError && <LemonBanner type="error">{queryError}</LemonBanner>}
            {onAskAI && (
                <div className="flex flex-wrap gap-2">
                    {(
                        [
                            ['write', 'Improve with AI'],
                            ['explain', 'Explain query'],
                            ...(queryError ? [['fix', 'Fix with AI']] : []),
                        ] as [InvestigationQueryTask, string][]
                    ).map(([task, label]) => (
                        <AIConsentPopoverWrapper key={task} onApprove={() => onAskAI(task, selected.id)}>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                onClick={() => onAskAI(task, selected.id)}
                                data-attr={`investigation-query-${task}`}
                            >
                                {label}
                            </LemonButton>
                        </AIConsentPopoverWrapper>
                    ))}
                </div>
            )}
        </>
    )
}
