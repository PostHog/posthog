import { useActions, useValues } from 'kea'

import { IconDocument } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { dataAgeLabel, isMaterializePayload, readSummary, refreshLabel, savingHighlight } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DataAgeMeta } from './DataAgeMeta'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { SuggestionRow } from './SuggestionRow'
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
            icon={<IconDocument />}
            title={
                <LemonTableLink
                    to={urls.sqlEditor({ view_id: suggestion.subject_id })}
                    title={<span className="truncate">{payload.subject_name}</span>}
                    truncateTitle
                />
            }
            meta={[
                <WhyThisSuggestion
                    key="reads"
                    evidence={suggestion.evidence}
                    windowDays={windowDays}
                    label={readSummary(suggestion.evidence)}
                />,
                <span key="refresh">{refreshLabel(payload.refresh_interval_seconds)}</span>,
                <DataAgeMeta key="age" age={dataAgeLabel(payload, payload.refresh_interval_seconds)} />,
            ]}
            highlight={savingHighlight(payload)}
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
                    <DismissSuggestionMenu suggestionId={suggestion.id} disabledReason={blockedReason} />
                </>
            }
        />
    )
}
