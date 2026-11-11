import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { certificationSummaryText, countOf } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRow } from './CertificationSuggestionRow'
import { DeprecateSuggestionModal } from './DeprecateSuggestionModal'
import { SuggestionsBanner } from './SuggestionsBanner'
import { SuggestionsReviewModal } from './SuggestionsReviewModal'
import { SuggestionsStatusNotice } from './SuggestionsStatusNotice'

export function SuggestedCertificationsTableContent(): JSX.Element | null {
    const { stripState, listedSuggestions, surfaceSuggestions, status } = useValues(warehouseSuggestionsLogic)
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
                            <span translate="no">{`: ${certificationSummaryText(surfaceSuggestions)}`}</span>
                        </>
                    }
                />
            )}
            <SuggestionsReviewModal
                title="Certification suggestions"
                summary={certificationSummaryText(surfaceSuggestions)}
            >
                {listedSuggestions.map((suggestion) => (
                    <CertificationSuggestionRow key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
                ))}
            </SuggestionsReviewModal>
            <DeprecateSuggestionModal />
        </>
    )
}
