import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import type { FileSystemIconType } from '~/queries/schema/schema-general'

import type { ReportSourceSuggestionApi } from 'products/signals/frontend/generated/api.schemas'

import {
    captureInboxReportSourceSuggestionClicked,
    captureInboxReportSourceSuggestionShown,
} from '../../inboxAnalytics'
import type { SignalReport } from '../../types'
import { SOURCE_SUGGESTION_TARGETS } from '../../utils/sourceSuggestion'
import { getSourceProductMeta } from '../badges/sourceProductIcons'

/** A product the team doesn't use that would have given this report better evidence, shown after the evidence. */
export function ReportSourceSuggestion({
    report,
    suggestion,
}: {
    report: SignalReport
    suggestion: ReportSourceSuggestionApi
}): JSX.Element {
    const { url, actionLabel } = SOURCE_SUGGESTION_TARGETS[suggestion.product]

    useOnMountEffect(() => {
        captureInboxReportSourceSuggestionShown({ report, product: suggestion.product })
    })

    return (
        <LemonCard hoverEffect={false} className="p-3 shadow-none border-dashed">
            <div className="flex items-center gap-2 mb-2">
                <span
                    className="flex shrink-0 text-base group/colorful-product-icons colorful-product-icons-true"
                    aria-hidden
                >
                    {iconForType(suggestion.product as FileSystemIconType)}
                </span>
                <span className="truncate text-xs font-medium text-tertiary">
                    {getSourceProductMeta(suggestion.product)?.label} · Not set up in this project
                </span>
            </div>
            <p className="m-0 mb-2 text-sm">{suggestion.reason}</p>
            <div className="flex">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={url()}
                    sideIcon={<IconArrowRight />}
                    onClick={() => captureInboxReportSourceSuggestionClicked({ report, product: suggestion.product })}
                    data-attr="inbox-report-source-suggestion"
                >
                    {actionLabel}
                </LemonButton>
            </div>
        </LemonCard>
    )
}
