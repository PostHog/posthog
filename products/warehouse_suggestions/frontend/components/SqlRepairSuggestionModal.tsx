import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { QueryDiffViewer } from 'scenes/data-warehouse/editor/components/QueryDiffViewer'

import { isSqlRepairPayload } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export function SqlRepairSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight } = useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isSqlRepairPayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]

    return (
        <LemonModal
            isOpen
            closable={!inFlight}
            onClose={closeAcceptConfirm}
            title={`Review SQL repair for ${payload.subject_name}`}
            width={1000}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAcceptConfirm}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={inFlight}
                        onClick={() => confirmAccept()}
                        data-attr="warehouse-suggestions-sql-repair-confirm"
                    >
                        Apply SQL repair
                    </LemonButton>
                </>
            }
        >
            <div className="@container flex max-w-full flex-col gap-4">
                <div className="grid grid-cols-1 gap-3 @min-[42rem]:grid-cols-2">
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold text-secondary">Failure evidence</span>
                        <span className="text-sm whitespace-pre-wrap">{payload.failure_evidence}</span>
                    </div>
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold text-secondary">Expected effect</span>
                        <span className="text-sm whitespace-pre-wrap">{payload.expected_effect}</span>
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">Reason</span>
                    <span className="text-sm whitespace-pre-wrap">{payload.reason}</span>
                </div>
                <div className="flex flex-col gap-2">
                    <span className="text-xs font-semibold text-secondary">Exact SQL change</span>
                    <QueryDiffViewer original={payload.original_query} modified={payload.proposed_query} />
                </div>
                <LemonBanner type="info">
                    PostHog checked the syntax, readable references, and result columns with a read-only query. The
                    query returned no result rows and had a {payload.validation.max_execution_seconds}-second limit. It
                    can read source rows while it checks the result columns. This check does not prove that the two
                    queries have the same business meaning. Acceptance changes only the SQL. It does not change the
                    schedule, incremental keys, permissions, or output columns.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
