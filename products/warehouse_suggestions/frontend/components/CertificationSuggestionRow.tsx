import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { daysReadLabel, isDeprecatePayload, noReadsLabel, readSummary, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { SuggestionRow } from './SuggestionRow'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view or table'
const TABLE_PREVIEW_LIMIT = 100

export interface CertificationSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

function subjectUrl(suggestion: WarehouseSuggestionApi): string {
    if (suggestion.subject_kind === 'table') {
        const table = escapePropertyAsHogQLIdentifier(suggestion.payload.subject_name)
        return urls.sqlEditor({ query: `SELECT * FROM ${table} LIMIT ${TABLE_PREVIEW_LIMIT}` })
    }
    return urls.sqlEditor({ view_id: suggestion.subject_id })
}

export function CertificationSuggestionRow({ suggestion, windowDays }: CertificationSuggestionRowProps): JSX.Element {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { acceptSuggestion, openAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    const isTable = suggestion.subject_kind === 'table'
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const inFlight = !!actionsInFlight[suggestion.id]
    const blockedReason = !suggestion.can_act ? EDIT_ACCESS_REASON : leaving ? 'Working' : undefined
    const deprecating = isDeprecatePayload(payload)

    return (
        <SuggestionRow
            suggestionId={suggestion.id}
            leaving={leaving}
            icon={
                <Tooltip title={isTable ? 'Table' : 'View'}>
                    <span className="flex" aria-label={isTable ? 'Table' : 'View'}>
                        {iconForType(isTable ? 'data_warehouse' : 'data_modeling')}
                    </span>
                </Tooltip>
            }
            title={
                <Link to={subjectUrl(suggestion)} subtle className="block min-w-0 truncate text-sm font-semibold">
                    {payload.subject_name}
                </Link>
            }
            meta={
                deprecating
                    ? [
                          <WhyThisSuggestion
                              key="reads"
                              evidence={suggestion.evidence}
                              windowDays={windowDays}
                              label={noReadsLabel(windowDays)}
                          />,
                          <span key="cost">{refreshCostLabel(payload)}</span>,
                      ]
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
                        disabledReason={blockedReason}
                        onClick={() =>
                            deprecating ? openAcceptConfirm(suggestion.id) : acceptSuggestion(suggestion.id)
                        }
                        data-attr={`warehouse-suggestions-${suggestion.kind}`}
                    >
                        {deprecating ? 'Mark deprecated' : 'Certify'}
                    </LemonButton>
                    <DismissSuggestionMenu
                        suggestionId={suggestion.id}
                        disabledReason={blockedReason ?? (inFlight ? 'Working' : undefined)}
                    />
                </>
            }
        />
    )
}
