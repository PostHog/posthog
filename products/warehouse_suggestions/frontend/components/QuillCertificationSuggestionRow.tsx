import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { certificationSuggestionGuards } from '../certificationSuggestionGuards'
import { daysReadLabel, isDeprecatePayload, noReadsLabel, readSummary, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRowProps } from './CertificationSuggestionRow'
import { QuillDismissSuggestionButtons } from './QuillDismissSuggestionButtons'
import { QuillSuggestionRow } from './QuillSuggestionRow'
import { QuillSuggestionSubjectLink } from './QuillSuggestionSubjectLink'
import { QuillWhyThisSuggestion } from './QuillWhyThisSuggestion'

export function QuillCertificationSuggestionRow({
    suggestion,
    windowDays,
}: CertificationSuggestionRowProps): JSX.Element {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { acceptSuggestion, openAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const inFlight = !!actionsInFlight[suggestion.id]
    const deprecating = isDeprecatePayload(payload)
    const { isTable, confirmsFirst, acceptBlockedReason, dismissBlockedReason } = certificationSuggestionGuards(
        suggestion,
        leaving,
        inFlight
    )
    const refreshes = deprecating && payload.materialized !== false
    const subjectLabel = isTable ? 'Table' : 'View'

    return (
        <QuillSuggestionRow
            suggestionId={suggestion.id}
            assignee={suggestion.assignee}
            canAct={suggestion.can_act}
            leaving={leaving}
            icon={
                <Tooltip>
                    <TooltipTrigger render={<span className="flex" aria-label={subjectLabel} />}>
                        {iconForType(isTable ? 'data_warehouse' : 'data_modeling')}
                    </TooltipTrigger>
                    <TooltipContent>{subjectLabel}</TooltipContent>
                </Tooltip>
            }
            title={<QuillSuggestionSubjectLink suggestion={suggestion} />}
            meta={
                deprecating
                    ? [
                          <QuillWhyThisSuggestion
                              key="reads"
                              evidence={suggestion.evidence}
                              windowDays={windowDays}
                              label={noReadsLabel(windowDays)}
                          />,
                          refreshes && <span key="cost">{refreshCostLabel(payload)}</span>,
                      ].filter(Boolean)
                    : [
                          <QuillWhyThisSuggestion
                              key="reads"
                              evidence={suggestion.evidence}
                              windowDays={windowDays}
                              label={readSummary(suggestion.evidence)}
                          />,
                          <span key="days">{daysReadLabel(suggestion.evidence, windowDays)}</span>,
                      ]
            }
            actions={
                <>
                    <Button
                        variant="outline"
                        loading={inFlight}
                        disabledReason={acceptBlockedReason}
                        onClick={() =>
                            confirmsFirst ? openAcceptConfirm(suggestion.id) : acceptSuggestion(suggestion.id)
                        }
                        data-attr={`warehouse-suggestions-${suggestion.kind}`}
                    >
                        {deprecating ? <IconWarning /> : <IconCheckCircle />}
                        {deprecating ? 'Mark deprecated' : 'Certify'}
                    </Button>
                    <QuillDismissSuggestionButtons
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={dismissBlockedReason}
                    />
                </>
            }
        />
    )
}
