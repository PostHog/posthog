import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import type { ReportSourceSuggestionApi } from 'products/signals/frontend/generated/api.schemas'

import {
    captureInboxReportSourceSuggestionClicked,
    captureInboxReportSourceSuggestionShown,
} from '../../inboxAnalytics'
import type { SignalReport } from '../../types'
import { SourceSuggestionTarget, sourceSuggestionTarget } from '../../utils/sourceSuggestion'

/** Where a source suggestion leads and its analytics, shared by the Lemon and quill suggestion cards. */
export function useReportSourceSuggestion(
    report: SignalReport,
    suggestion: ReportSourceSuggestionApi
): { target: SourceSuggestionTarget | null; onClick: () => void } {
    const target = sourceSuggestionTarget(suggestion.product)

    useOnMountEffect(() => {
        if (target) {
            captureInboxReportSourceSuggestionShown({ report, product: suggestion.product })
        }
    })

    return {
        target,
        onClick: () => captureInboxReportSourceSuggestionClicked({ report, product: suggestion.product }),
    }
}
