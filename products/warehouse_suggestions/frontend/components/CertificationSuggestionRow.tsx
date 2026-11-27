import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { certificationSuggestionGuards } from '../certificationSuggestionGuards'
import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { daysReadLabel, isDeprecatePayload, noReadsLabel, readSummary, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionButtons } from './DismissSuggestionButtons'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'
import { WhyThisSuggestion } from './WhyThisSuggestion'

export interface CertificationSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

export function CertificationSuggestionRow({ suggestion, windowDays }: CertificationSuggestionRowProps): JSX.Element {
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

    return (
        <SuggestionRow
            suggestionId={suggestion.id}
            assignee={suggestion.assignee}
            canAct={suggestion.can_act}
            leaving={leaving}
            icon={
                <Tooltip title={isTable ? 'Table' : 'View'}>
                    <span className="flex" aria-label={isTable ? 'Table' : 'View'}>
                        {iconForType(isTable ? 'data_warehouse' : 'data_modeling')}
                    </span>
                </Tooltip>
            }
            title={<SuggestionSubjectLink suggestion={suggestion} />}
            meta={
                deprecating
                    ? [
                          <WhyThisSuggestion
                              key="reads"
                              evidence={suggestion.evidence}
                              windowDays={windowDays}
                              label={noReadsLabel(windowDays)}
                          />,
                          refreshes && <span key="cost">{refreshCostLabel(payload)}</span>,
                      ].filter(Boolean)
                    : [
                          <WhyThisSuggestion
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
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={deprecating ? <IconWarning /> : <IconCheckCircle />}
                        loading={inFlight}
                        disabledReason={acceptBlockedReason}
                        onClick={() =>
                            confirmsFirst ? openAcceptConfirm(suggestion.id) : acceptSuggestion(suggestion.id)
                        }
                        data-attr={`warehouse-suggestions-${suggestion.kind}`}
                    >
                        {deprecating ? 'Mark deprecated' : 'Certify'}
                    </LemonButton>
                    <DismissSuggestionButtons
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={dismissBlockedReason}
                    />
                </>
            }
        />
    )
}
