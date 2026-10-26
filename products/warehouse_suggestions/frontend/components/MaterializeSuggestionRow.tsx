import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { dataAgeLabel, isMaterializePayload, materializeSaving, readSummary, savingHighlight } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DataAgeMeta } from './DataAgeMeta'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view'

export interface MaterializeSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

export function MaterializeSuggestionRow({
    suggestion,
    windowDays,
}: MaterializeSuggestionRowProps): JSX.Element | null {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { openMaterializeModal } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    if (!isMaterializePayload(payload)) {
        return null
    }
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const blockedReason = !suggestion.can_act
        ? EDIT_ACCESS_REASON
        : actionsInFlight[suggestion.id] || leaving
          ? 'Working'
          : undefined

    return (
        <SuggestionRow
            suggestionId={suggestion.id}
            leaving={leaving}
            icon={iconForType('data_modeling')}
            title={<SuggestionSubjectLink suggestion={suggestion} />}
            meta={[
                <WhyThisSuggestion
                    key="reads"
                    evidence={suggestion.evidence}
                    windowDays={windowDays}
                    label={readSummary(suggestion.evidence)}
                />,
                <DataAgeMeta key="age" age={dataAgeLabel(payload, payload.refresh_interval_seconds)} />,
                ...(payload.refresh_mode === 'incremental'
                    ? [<span key="mode">{`Incremental by ${payload.incremental_key ?? 'new rows'}`}</span>]
                    : []),
            ]}
            highlight={savingHighlight(materializeSaving(payload))}
            actions={
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={blockedReason}
                        onClick={() => openMaterializeModal(suggestion.id)}
                        data-attr="warehouse-suggestions-materialize"
                    >
                        Materialize
                    </LemonButton>
                    <DismissSuggestionMenu
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={blockedReason}
                    />
                </>
            }
        />
    )
}
