import { useActions, useValues } from 'kea'

import { IconLightBulb, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { MaterializeSuggestionModal } from './MaterializeSuggestionModal'
import { MaterializeSuggestionRow } from './MaterializeSuggestionRow'
import { SavingsBannerMessage } from './SavingsBannerMessage'
import { SuggestionsBanner } from './SuggestionsBanner'
import { SuggestionsReviewModal } from './SuggestionsReviewModal'
import { SuggestionsStatusNotice } from './SuggestionsStatusNotice'
import { UnmaterializeSuggestionModal } from './UnmaterializeSuggestionModal'
import { UnmaterializeSuggestionRow } from './UnmaterializeSuggestionRow'

export function SuggestedModelsStripContent(): JSX.Element | null {
    const { stripState, listedSuggestions, savingsSummary, status } = useValues(warehouseSuggestionsLogic)
    const { reload } = useActions(warehouseSuggestionsLogic)
    const windowDays = status?.window_days ?? 0

    if (stripState === 'error') {
        return (
            <SuggestionsStatusNotice
                icon={<IconWarning className="text-warning" />}
                message="Couldn't load suggested models."
                extra={
                    <LemonButton size="xsmall" type="secondary" onClick={() => reload()}>
                        Retry
                    </LemonButton>
                }
            />
        )
    }
    if (stripState === 'warming_up') {
        const daysWithData = status?.days_with_data ?? 0
        return (
            <SuggestionsStatusNotice
                icon={<IconLightBulb />}
                message="Suggested models get better as read history builds up."
                extra={
                    <span className="flex shrink-0 items-center gap-2 whitespace-nowrap text-xs text-secondary">
                        <span className="w-24 shrink-0">
                            <LemonProgress percent={windowDays ? (daysWithData / windowDays) * 100 : 0} />
                        </span>
                        <span translate="no" className="tabular-nums">{`${daysWithData} of ${windowDays} days`}</span>
                    </span>
                }
            />
        )
    }
    if (stripState === 'not_eligible') {
        return (
            <SuggestionsStatusNotice
                icon={<IconLightBulb />}
                message="Suggested models start once people in this project read its views regularly."
            />
        )
    }
    if (stripState !== 'active' && stripState !== 'all_done') {
        return null
    }

    return (
        <>
            {stripState === 'active' && (
                <SuggestionsBanner
                    icon={iconForType('data_modeling')}
                    message={<SavingsBannerMessage summary={savingsSummary} />}
                />
            )}
            <SuggestionsReviewModal
                title="Suggested models"
                summary={<SavingsBannerMessage summary={savingsSummary} />}
            >
                {listedSuggestions.map((suggestion) =>
                    suggestion.kind === 'unmaterialize' ? (
                        <UnmaterializeSuggestionRow
                            key={suggestion.id}
                            suggestion={suggestion}
                            windowDays={windowDays}
                        />
                    ) : (
                        <MaterializeSuggestionRow key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
                    )
                )}
            </SuggestionsReviewModal>
            <MaterializeSuggestionModal />
            <UnmaterializeSuggestionModal />
        </>
    )
}
