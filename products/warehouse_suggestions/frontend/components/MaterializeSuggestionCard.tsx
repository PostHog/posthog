import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { freshnessSentence, isMaterializePayload, readSentence, savingPhrase } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view'

export interface MaterializeSuggestionCardProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

export function MaterializeSuggestionCard({
    suggestion,
    windowDays,
}: MaterializeSuggestionCardProps): JSX.Element | null {
    const { actionsInFlight } = useValues(warehouseSuggestionsLogic)
    const { openMaterializeModal } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    if (!isMaterializePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[suggestion.id]
    const blockedReason = !suggestion.can_act ? EDIT_ACCESS_REASON : inFlight ? 'Working' : undefined

    return (
        <LemonCard hoverEffect={false} className="@container flex flex-col gap-2 p-3">
            <LemonTableLink
                to={urls.sqlEditor({ view_id: suggestion.subject_id })}
                title={payload.subject_name}
                truncateTitle
            />
            <p className="m-0 text-sm text-secondary">
                <span>{readSentence(suggestion.evidence, windowDays)}</span> Materializing saves{' '}
                <strong>{savingPhrase(payload)}</strong> a month. <span>{freshnessSentence(payload)}</span>
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <WhyThisSuggestion evidence={suggestion.evidence} windowDays={windowDays} />
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabledReason={blockedReason}
                    onClick={() => openMaterializeModal(suggestion.id)}
                    data-attr="warehouse-suggestions-materialize"
                >
                    Materialize
                </LemonButton>
                <DismissSuggestionMenu suggestionId={suggestion.id} disabledReason={blockedReason} />
            </div>
        </LemonCard>
    )
}
