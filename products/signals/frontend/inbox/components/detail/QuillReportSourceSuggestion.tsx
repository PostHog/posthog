import { IconArrowRight } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import type { FileSystemIconType } from '~/queries/schema/schema-general'

import type { ReportSourceSuggestionApi } from 'products/signals/frontend/generated/api.schemas'

import type { SignalReport } from '../../types'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { useReportSourceSuggestion } from './useReportSourceSuggestion'

/** Quill sibling of `ReportSourceSuggestion`: a product the team doesn't use that would have given this report better evidence. */
export function QuillReportSourceSuggestion({
    report,
    suggestion,
}: {
    report: SignalReport
    suggestion: ReportSourceSuggestionApi
}): JSX.Element | null {
    const { target, onClick } = useReportSourceSuggestion(report, suggestion)

    if (!target) {
        return null
    }

    // Dashed and unfilled rather than a Card, so the suggestion reads as an offer, not as more evidence.
    return (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border p-3">
            <div className="flex min-w-0 items-center gap-2">
                <span
                    className="flex shrink-0 text-base group/colorful-product-icons colorful-product-icons-true"
                    aria-hidden
                >
                    {iconForType(suggestion.product as FileSystemIconType)}
                </span>
                <Text size="xs" weight="medium" variant="muted" render={<span />} className="truncate">
                    {`${getSourceProductMeta(suggestion.product)?.label} · Not set up in this project`}
                </Text>
            </div>
            <Text size="xs" className="m-0">
                {suggestion.reason}
            </Text>
            <Button
                variant="outline"
                nativeButton={false}
                render={<LinkPrimitive to={target.url()} />}
                onClick={onClick}
                data-attr="inbox-report-source-suggestion"
                className="self-start"
            >
                {target.actionLabel}
                <IconArrowRight />
            </Button>
        </div>
    )
}
