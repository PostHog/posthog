import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { certificationSummaryText } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { CertificationSuggestionRow } from './CertificationSuggestionRow'
import { SuggestionsSection } from './SuggestionsSection'
import { SuggestionsStatusNotice } from './SuggestionsStatusNotice'

export function SuggestedCertificationsTableContent(): JSX.Element | null {
    const { stripState, visibleSuggestions, surfaceSuggestions, status } = useValues(warehouseSuggestionsLogic)
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
        <SuggestionsSection title="Certification suggestions" summary={certificationSummaryText(surfaceSuggestions)}>
            {visibleSuggestions.map((suggestion) => (
                <CertificationSuggestionRow key={suggestion.id} suggestion={suggestion} windowDays={windowDays} />
            ))}
        </SuggestionsSection>
    )
}
