import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { userHasAccess } from 'lib/utils/accessControlUtils'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { daysReadLabel, isDeprecatePayload, noReadsLabel, readSummary, refreshCostLabel } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view or table'
const CATALOG_EDIT_ACCESS_REASON = 'You need edit access to the data catalog'

export interface CertificationSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

export function CertificationSuggestionRow({ suggestion, windowDays }: CertificationSuggestionRowProps): JSX.Element {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { acceptSuggestion, openAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    const isTable = suggestion.subject_kind === 'table'
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const inFlight = !!actionsInFlight[suggestion.id]
    const blockedReason = !suggestion.can_act ? EDIT_ACCESS_REASON : leaving ? 'Working' : undefined
    const acceptBlockedReason =
        blockedReason ??
        (userHasAccess(AccessControlResourceType.DataCatalog, AccessControlLevel.Editor)
            ? undefined
            : CATALOG_EDIT_ACCESS_REASON)
    const deprecating = isDeprecatePayload(payload)
    const confirmsFirst = deprecating && !isTable

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
                        disabledReason={acceptBlockedReason}
                        onClick={() =>
                            confirmsFirst ? openAcceptConfirm(suggestion.id) : acceptSuggestion(suggestion.id)
                        }
                        data-attr={`warehouse-suggestions-${suggestion.kind}`}
                    >
                        {deprecating ? 'Mark deprecated' : 'Certify'}
                    </LemonButton>
                    <DismissSuggestionMenu
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={blockedReason ?? (inFlight ? 'Working' : undefined)}
                    />
                </>
            }
        />
    )
}
