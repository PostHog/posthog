import { ReactNode } from 'react'

import { Badge, Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { formatEventName } from 'lib/insights/entityFilterNames'
import type { ResultSeries } from 'scenes/insights/utils/resultSeries'

import { QuillMathBadge } from './QuillMathBadge'

interface QuillSeriesLabelProps {
    series: ResultSeries
    /** The name to show when the row has no series to name, such as a formula. */
    fallbackName?: string
    showCountedByTag: boolean
    /** "Current" or "Previous", for a row of a compared period. */
    compareValue?: string
    emphasize: boolean
    onRename?: () => void
    nameTooltip?: string
    /** Shown right after the name, before the tags. */
    swatch?: ReactNode
}

export function QuillSeriesLabel({
    series,
    fallbackName,
    showCountedByTag,
    compareValue,
    emphasize,
    onRename,
    nameTooltip,
    swatch,
}: QuillSeriesLabelProps): JSX.Element {
    const entity = series.node
    const math = series.math
    const name = entity ? (
        <EntityFilterInfo filter={{ ...entity, name: formatEventName(entity.name) }} />
    ) : (
        <PropertyKeyInfo
            disableIcon
            disablePopover
            value={formatEventName(fallbackName) || ''}
            type={TaxonomicFilterGroupType.Events}
        />
    )

    return (
        <span className={cn('flex min-w-0 items-center gap-2', emphasize && 'font-medium')}>
            {onRename ? (
                <Button
                    variant="link-foreground"
                    size="sm"
                    tooltip={nameTooltip ?? 'Rename series'}
                    onClick={onRename}
                    className="-mx-2 min-w-0"
                >
                    {name}
                </Button>
            ) : nameTooltip ? (
                <Tooltip>
                    <TooltipTrigger render={<span className="min-w-0" />}>{name}</TooltipTrigger>
                    <TooltipContent>{nameTooltip}</TooltipContent>
                </Tooltip>
            ) : (
                <span className="min-w-0">{name}</span>
            )}
            {swatch}
            {((math?.math && math.math !== 'total') || showCountedByTag) && <QuillMathBadge math={math} />}
            {compareValue && <Badge>{compareValue}</Badge>}
        </span>
    )
}
