import { Item, ItemContent, ItemDescription, ItemHeader, ItemTitle, Skeleton, cn } from '@posthog/quill'

import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { ChartDisplayIcon } from 'products/product_analytics/frontend/insights/chartAlternatives/ChartDisplayIcon'
import { ChartPreviewCanvas } from 'products/product_analytics/frontend/insights/chartAlternatives/ChartPreviewCanvas'

import type { ChartTypeTilePreview } from './chartTypeStripLogic'

const PREVIEW_CONTEXT: QueryContext<InsightVizNode> = { hideAxes: true, bareChart: true }

export interface ChartTypeTileProps {
    tile: ChartTypeTilePreview
    loading: boolean
    onSelect: () => void
}

export function ChartTypeTile({ tile, loading, onSelect }: ChartTypeTileProps): JSX.Element {
    const { option, query, response, sample, uniqueKey } = tile
    const chartShown = !!response && !loading

    return (
        <Item
            variant="outline"
            size="sm"
            render={<button type="button" />}
            className={cn(
                'w-48 content-start rounded-(--radius-md) bg-(--card) text-start text-foreground shadow-(--shadow-sm)',
                'focus-visible:ring-2 focus-visible:ring-(--ring)/30',
                loading
                    ? 'cursor-progress'
                    : 'cursor-pointer hover:border-(--foreground)/25 active:translate-y-px active:shadow-none'
            )}
            aria-busy={loading || undefined}
            aria-disabled={loading || undefined}
            onClick={loading ? undefined : onSelect}
            data-attr="quill-insight-chart-type-tile"
            data-chart-type={option.display}
        >
            <ItemHeader
                aria-hidden
                className="pointer-events-none h-20 flex-col items-stretch overflow-hidden rounded-(--radius-sm) bg-(--muted)/50 p-1"
            >
                {loading ? (
                    <Skeleton className="h-full w-full" />
                ) : response ? (
                    <div
                        className={cn(
                            'flex h-full min-h-0 flex-col [&_.text-7xl]:text-lg [&_.text-7xl]:leading-tight',
                            chartShown && option.display === ChartDisplayType.BoldNumber && '[&_.BoldNumber]:p-4',
                            // MetricCard hardcodes its headline at text-4xl, which truncates at tile width.
                            chartShown &&
                                option.display === ChartDisplayType.Metric &&
                                '[&_.text-4xl]:text-lg [&_.text-4xl]:leading-tight'
                        )}
                    >
                        <ChartPreviewCanvas
                            uniqueKey={uniqueKey}
                            query={query}
                            response={response}
                            context={PREVIEW_CONTEXT}
                        />
                    </div>
                ) : (
                    <span className="flex flex-1 items-center justify-center text-2xl text-muted-foreground">
                        <ChartDisplayIcon icon={option.icon} />
                    </span>
                )}
            </ItemHeader>
            <ItemContent className="min-w-0">
                <ItemTitle className="w-full">
                    <span aria-hidden className="flex shrink-0 text-muted-foreground">
                        <ChartDisplayIcon icon={option.icon} />
                    </span>
                    <span className="min-w-0 truncate">{option.label}</span>
                </ItemTitle>
                {sample && !loading ? <ItemDescription>Sample data</ItemDescription> : null}
            </ItemContent>
        </Item>
    )
}
