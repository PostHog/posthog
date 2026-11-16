import { useValues } from 'kea'
import { ReactElement, useState } from 'react'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

interface TaxonomicBreakdownButtonProps {
    disabledReason?: ReactElement | string
    disabledReasonInteractive?: boolean
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownButton({
    disabledReason,
    disabledReasonInteractive,
    size,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)
    const quillSurface = useQuillSurface()

    const isCohortBreakdown = taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
    const docsUrl = isCohortBreakdown
        ? 'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'
        : 'https://posthog.com/docs/product-analytics/trends/breakdowns'
    const label = isCohortBreakdown ? 'Cohort' : 'Breakdown'

    if (quillSurface) {
        return (
            <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
                <Button
                    variant="outline"
                    data-attr="add-breakdown-button"
                    disabledReason={disabledReason}
                    tooltip={
                        <LinkPrimitive
                            to={docsUrl}
                            target="_blank"
                            className="text-xs text-primary-on-foreground underline"
                            data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                            data-ph-capture-attribute-doclink={docsUrl}
                        >
                            Read the docs
                        </LinkPrimitive>
                    }
                >
                    <IconPlus />
                    {label}
                </Button>
            </TaxonomicBreakdownPopover>
        )
    }

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
                disabledReason={disabledReason}
                disabledReasonInteractive={disabledReasonInteractive}
                size={size}
                // When a disabled reason is set, the docs link is embedded inline in the reason —
                // don't render it twice via tooltipDocLink.
                tooltipDocLink={disabledReason ? undefined : docsUrl}
            >
                {label}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
