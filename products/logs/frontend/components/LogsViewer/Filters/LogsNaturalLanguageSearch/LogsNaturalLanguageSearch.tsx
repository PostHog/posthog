import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { LogsNaturalLanguageCandidates } from './LogsNaturalLanguageCandidates'
import { logsNaturalLanguageSearchLogic } from './logsNaturalLanguageSearchLogic'
import { looksLikeNaturalLanguage } from './naturalLanguageSearch'

/** The AI row at the top of the logs search dropdown. Must render inside a bound taxonomicFilterLogic. */
export const LogsNaturalLanguageSearch = ({ onApplied }: { onApplied: () => void }): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { id } = useValues(logsViewerFiltersLogic)
    const { searchQuery } = useValues(taxonomicFilterLogic)
    const { setSearchQuery } = useActions(taxonomicFilterLogic)
    const logic = logsNaturalLanguageSearchLogic({ id })
    const { response, responseLoading, error, askedQuery, appliedCount } = useValues(logic)
    const { askAi, applyCandidate, reset } = useActions(logic)

    useEffect(() => {
        if (appliedCount > 0) {
            setSearchQuery('')
            onApplied()
        }
        // Only a new application should close the dropdown, not a change of callback identity.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [appliedCount])

    const trimmedQuery = searchQuery.trim()
    // A result belongs to the text it answered. Editing the text hides it until the person asks again.
    const showResult = askedQuery !== null && askedQuery === trimmedQuery

    if (!featureFlags[FEATURE_FLAGS.LOGS_NATURAL_LANGUAGE_SEARCH]) {
        return null
    }
    if (!looksLikeNaturalLanguage(trimmedQuery) && !showResult) {
        return null
    }

    return (
        <div className="flex flex-col gap-1 p-1 border-b">
            <LemonButton
                fullWidth
                size="small"
                icon={<IconSparkles />}
                loading={responseLoading}
                disabledReason={responseLoading ? 'Turning your request into filters' : undefined}
                onClick={() => askAi(trimmedQuery)}
                data-attr="logs-natural-language-ask"
            >
                <span className="truncate">Turn "{trimmedQuery}" into filters with AI</span>
            </LemonButton>
            {showResult && !responseLoading && error ? (
                <div className="text-xs text-danger px-2">{error}</div>
            ) : showResult && !responseLoading && response && response.candidates.length === 0 ? (
                <div className="text-xs text-secondary px-2">
                    No filters matched that request. Name a service, level or time range and try again.
                </div>
            ) : showResult && !responseLoading && response && response.candidates.length > 0 ? (
                <>
                    <LogsNaturalLanguageCandidates
                        candidates={response.candidates}
                        onApply={(candidate, rank) => applyCandidate(candidate, rank, false)}
                    />
                    <LemonButton size="xsmall" onClick={() => reset()} data-attr="logs-natural-language-dismiss">
                        Dismiss
                    </LemonButton>
                </>
            ) : null}
        </div>
    )
}
