import { useActions, useValues } from 'kea'

import { IconArchive, IconCheckCircle } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { certificationSuggestionGuards } from '../certificationSuggestionGuards'
import { daysReadLabel, isDeprecatePayload, noReadsLabel, readSummary, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRowProps } from './CertificationSuggestionRow'
import { QuillSuggestionActions } from './QuillSuggestionActions'
import { QuillRowSelectionProps, QuillSuggestionRow } from './QuillSuggestionRow'
import { QuillSuggestionSubjectLink } from './QuillSuggestionSubjectLink'
import { QuillWhyThisSuggestion } from './QuillWhyThisSuggestion'

export function QuillCertificationSuggestionRow({
    suggestion,
    windowDays,
    selection,
}: CertificationSuggestionRowProps & QuillRowSelectionProps): JSX.Element {
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
            selection={selection}
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
                <QuillSuggestionActions
                    suggestion={suggestion}
                    label={deprecating ? 'Mark deprecated' : 'Certify'}
                    icon={deprecating ? <IconArchive /> : <IconCheckCircle />}
                    onAccept={() =>
                        confirmsFirst ? openAcceptConfirm(suggestion.id) : acceptSuggestion(suggestion.id)
                    }
                    acceptBlockedReason={acceptBlockedReason}
                    dismissBlockedReason={dismissBlockedReason}
                    loading={inFlight}
                    acceptDataAttr={`warehouse-suggestions-${suggestion.kind}`}
                />
            }
        />
    )
}
