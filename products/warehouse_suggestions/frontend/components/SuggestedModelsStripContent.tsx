import { useActions, useValues } from 'kea'

import { IconLightBulb, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRow } from './CertificationSuggestionRow'
import { DeprecateSuggestionModal } from './DeprecateSuggestionModal'
import { MaterializeSuggestionModal } from './MaterializeSuggestionModal'
import { MaterializeSuggestionRow } from './MaterializeSuggestionRow'
import { SavingsBannerMessage } from './SavingsBannerMessage'
import { SuggestedModelsSection } from './SuggestedModelsSection'
import { SuggestionsBanner } from './SuggestionsBanner'
import { SuggestionsReviewModal } from './SuggestionsReviewModal'
import { SuggestionsStatusNotice } from './SuggestionsStatusNotice'
import { UnmaterializeSuggestionModal } from './UnmaterializeSuggestionModal'
import { UnmaterializeSuggestionRow } from './UnmaterializeSuggestionRow'

const SECTION_COPY: Record<string, { title: string; description: string; showsSaving?: boolean }> = {
    materialize: {
        title: 'Materialize',
        description: 'Store these views so reads and other refreshes can reuse their results.',
    },
    unmaterialize: {
        title: 'Stop materializing',
        description: 'These views cost more to refresh than to run on each read.',
    },
    deprecate: {
        title: 'Mark deprecated',
        description: 'No one has read these views recently.',
        showsSaving: false,
    },
}

const ROW_FOR_KIND: Record<
    string,
    (props: { suggestion: WarehouseSuggestionApi; windowDays: number }) => JSX.Element | null
> = {
    materialize: MaterializeSuggestionRow,
    unmaterialize: UnmaterializeSuggestionRow,
    deprecate: CertificationSuggestionRow,
}

export function SuggestedModelsStripContent(): JSX.Element | null {
    const { stripState, suggestionGroups, savingsSummary, surfaceSuggestions, status } =
        useValues(warehouseSuggestionsLogic)
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

    const unusedViews = surfaceSuggestions.filter((suggestion) => suggestion.kind === 'deprecate').length
    const summary = <SavingsBannerMessage summary={savingsSummary} unusedViews={unusedViews} />

    return (
        <>
            {stripState === 'active' && <SuggestionsBanner icon={iconForType('data_modeling')} message={summary} />}
            <SuggestionsReviewModal title="Suggested models" summary={summary}>
                {suggestionGroups.map(({ kind, suggestions }) => (
                    <SuggestedModelsSection key={kind} {...SECTION_COPY[kind]}>
                        {suggestions.map((suggestion) => {
                            const RowComponent = ROW_FOR_KIND[kind] ?? MaterializeSuggestionRow
                            return <RowComponent key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
                        })}
                    </SuggestedModelsSection>
                ))}
            </SuggestionsReviewModal>
            <MaterializeSuggestionModal />
            <UnmaterializeSuggestionModal />
            <DeprecateSuggestionModal />
        </>
    )
}
