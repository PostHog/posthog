import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { InvestigationDocument } from './investigationDocument'
import {
    InvestigationQueryProposal as QueryProposal,
    InvestigationQueryRequest,
    proposalReplacementReason,
} from './queryAssistantHelpers'

export function InvestigationQueryProposal({
    document,
    request,
    proposal,
    onAccept,
    onDismiss,
}: {
    document: InvestigationDocument
    request: InvestigationQueryRequest
    proposal: QueryProposal
    onAccept: (mode: 'replace' | 'add') => void
    onDismiss: () => void
}): JSX.Element {
    const target = document.evidence.find((item) => item.id === request.targetId)
    const replacementReason = proposalReplacementReason(target, request)
    return (
        <div
            className="flex flex-col gap-3 border rounded p-4 bg-surface-primary"
            data-attr="investigation-query-proposal"
        >
            <div>
                <h3 className="text-base m-0">Review suggested query</h3>
                <p className="text-secondary text-sm mb-0">
                    Review the suggested SQL and the assistant's explanation before saving it as evidence.
                </p>
            </div>
            {request.targetId && replacementReason && <LemonBanner type="warning">{replacementReason}</LemonBanner>}
            {request.originalSql && (
                <details>
                    <summary className="cursor-pointer text-secondary">Original query</summary>
                    <pre className="whitespace-pre-wrap break-words text-xs mt-2" translate="no">
                        {request.originalSql}
                    </pre>
                </details>
            )}
            <pre
                className="whitespace-pre-wrap break-words text-xs m-0 border rounded p-3 max-h-80 overflow-y-auto"
                translate="no"
            >
                {proposal.sql}
            </pre>
            <div className="flex flex-wrap gap-2">
                {request.targetId && (
                    <LemonButton
                        type="primary"
                        size="small"
                        disabledReason={replacementReason}
                        onClick={() => onAccept('replace')}
                        data-attr="investigation-use-ai-query"
                    >
                        Use query
                    </LemonButton>
                )}
                <LemonButton
                    type={request.targetId ? 'secondary' : 'primary'}
                    size="small"
                    onClick={() => onAccept('add')}
                    disabledReason={
                        document.evidence.length >= 12
                            ? 'An investigation supports up to 12 evidence items.'
                            : undefined
                    }
                    data-attr="investigation-add-ai-query"
                >
                    Add as new evidence
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={onDismiss}
                    data-attr="investigation-discard-ai-query"
                >
                    Discard
                </LemonButton>
            </div>
            <p className="text-xs text-secondary mb-0">
                Saved runs and the baseline stay unchanged. Run evidence after accepting to capture a new snapshot.
            </p>
        </div>
    )
}
