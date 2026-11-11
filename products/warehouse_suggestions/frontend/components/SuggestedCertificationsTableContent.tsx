import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { suggestionCountsText, countOf } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRow } from './CertificationSuggestionRow'
import { DeprecateSuggestionModal } from './DeprecateSuggestionModal'
import { SuggestionsBanner } from './SuggestionsBanner'
import { SuggestionsReviewModal } from './SuggestionsReviewModal'
import { SuggestionsStatusNotice } from './SuggestionsStatusNotice'
import { WaitingSuggestionsNotice } from './WaitingSuggestionsNotice'

export function SuggestedCertificationsTableContent(): JSX.Element | null {
    const { stripState, listedSuggestions, surfaceSuggestions, status, showWaitingNotice } =
        useValues(warehouseSuggestionsLogic)
    const { reload } = useActions(warehouseSuggestionsLogic)
    const windowDays = status?.window_days ?? 0

    if (stripState === 'error') {
        return (
            <SuggestionsStatusNotice
                icon={<IconWarning className="text-warning" />}
                message="Couldn't load certification suggestions."
                extra={
                    <LemonButton size="xsmall" type="secondary" onClick={() => reload()}>
                        Retry
                    </LemonButton>
                }
            />
        )
    }
    if (showWaitingNotice && stripState !== 'active' && stripState !== 'all_done') {
        return <WaitingSuggestionsNotice />
    }
    if (stripState !== 'active' && stripState !== 'all_done') {
        return null
    }

    return (
        <>
            {stripState === 'active' && (
                <SuggestionsBanner
                    icon={iconForType('data_catalog')}
                    message={
                        <>
                            <strong translate="no">
                                {countOf(
                                    surfaceSuggestions.length,
                                    'certification suggestion',
                                    'certification suggestions'
                                )}
                            </strong>
                            <span translate="no">{`: ${suggestionCountsText(surfaceSuggestions)}`}</span>
                        </>
                    }
                />
            )}
            {showWaitingNotice && <WaitingSuggestionsNotice />}
            <SuggestionsReviewModal
                title="Certification suggestions"
                summary={suggestionCountsText(surfaceSuggestions)}
            >
                {listedSuggestions.map((suggestion) => (
                    <CertificationSuggestionRow key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
                ))}
            </SuggestionsReviewModal>
            <DeprecateSuggestionModal />
        </>
    )
}
