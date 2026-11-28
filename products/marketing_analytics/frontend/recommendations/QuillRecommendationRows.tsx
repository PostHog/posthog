import { Fragment, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Badge, Button, cn, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { QuillRecommendationCpa } from './QuillRecommendationCpa'
import { QUILL_DIRECTION_BADGE } from './QuillRecommendationImpactTotals'
import { QuillRecommendationResolutionButtons } from './QuillRecommendationResolutionButtons'
import { QuillRecommendationSteps } from './QuillRecommendationSteps'
import {
    IMPACT_DIRECTION_LABELS,
    impactColumnTitle,
    RECOMMENDATION_RULE_LABELS,
    RECOMMENDATIONS_PAGE_SIZE,
} from './recommendations'

const LAYOUT_BREAKPOINTS: Record<number, 'stacked' | 'columns'> = { 0: 'stacked', 640: 'columns' }

export function QuillRecommendationRows({
    rows,
    keepOnly,
    showRule,
    expanded,
    onToggle,
}: {
    rows: MarketingAnalyticsRecommendation[]
    keepOnly: boolean
    showRule: boolean
    expanded: Set<string>
    onToggle: (key: string, rule: MarketingAnalyticsRecommendation['rule']) => void
}): JSX.Element {
    // The action column does not fit a narrow dialog, so there the actions go under the recommendation.
    // Measured rather than a container query, so each row renders one set of action buttons.
    const { ref, size } = useResizeBreakpoints(LAYOUT_BREAKPOINTS, { initialSize: 'columns' })
    const stacked = size === 'stacked'
    const [page, setPage] = useState(1)
    const pageCount = Math.max(1, Math.ceil(rows.length / RECOMMENDATIONS_PAGE_SIZE))
    // Resolving or restoring the only row of the last page leaves that page empty.
    const currentPage = Math.min(page, pageCount)
    const pageRows = rows.slice((currentPage - 1) * RECOMMENDATIONS_PAGE_SIZE, currentPage * RECOMMENDATIONS_PAGE_SIZE)

    return (
        <div ref={ref} className="min-w-0">
            <Table fullWidth size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead>For</TableHead>
                        <TableHead expand>Recommendation</TableHead>
                        <TableHead align="right">{impactColumnTitle(keepOnly)}</TableHead>
                        {!stacked && <TableHead />}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {pageRows.map((row) => {
                        const hasSteps = !!row.steps?.length
                        const isExpanded = hasSteps && expanded.has(row.key)
                        return (
                            <Fragment key={row.key}>
                                <TableRow>
                                    <TableCell
                                        valign="top"
                                        className={cn('w-1/4 whitespace-normal break-words', !stacked && 'min-w-40')}
                                    >
                                        <div className="flex flex-col gap-0.5">
                                            <Text size="xs" weight="semibold" render={<span />}>
                                                {row.subject}
                                            </Text>
                                            {row.campaign && (
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    {row.campaign}
                                                </Text>
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell valign="top" expand className="whitespace-normal">
                                        <div className="flex flex-col items-start gap-0.5">
                                            {showRule && (
                                                <Text size="xs" variant="muted" weight="medium" render={<span />}>
                                                    {RECOMMENDATION_RULE_LABELS[row.rule]}
                                                </Text>
                                            )}
                                            <Text size="xs" render={<span className="text-pretty" />}>
                                                {row.action}
                                            </Text>
                                            <Text size="xs" variant="muted" render={<span />}>
                                                {row.reason}
                                            </Text>
                                            <QuillRecommendationCpa recommendation={row} />
                                            {hasSteps && (
                                                <Button
                                                    size="sm"
                                                    className="-ml-2"
                                                    aria-expanded={isExpanded}
                                                    onClick={() => onToggle(row.key, row.rule)}
                                                    data-attr="marketing-recommendations-view-instructions"
                                                >
                                                    <span>
                                                        {isExpanded ? 'Hide instructions' : 'View instructions'}
                                                    </span>
                                                    {isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                                </Button>
                                            )}
                                            {stacked && (
                                                <QuillRecommendationResolutionButtons recommendation={row} stacked />
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell valign="top" align="right">
                                        {row.impact == null ? (
                                            <Text size="xs" variant="muted" render={<span />}>
                                                –
                                            </Text>
                                        ) : (
                                            <div className="flex flex-col items-end gap-0.5">
                                                <Text
                                                    size="xs"
                                                    weight="semibold"
                                                    render={<span className="tabular-nums" translate="no" />}
                                                >
                                                    {`${formatMarketingMoney(row.impact, row.currency)}/mo`}
                                                </Text>
                                                <Badge variant={QUILL_DIRECTION_BADGE[row.impactDirection]}>
                                                    {row.impactType === 'estimated'
                                                        ? `${IMPACT_DIRECTION_LABELS[row.impactDirection]}, estimated`
                                                        : IMPACT_DIRECTION_LABELS[row.impactDirection]}
                                                </Badge>
                                            </div>
                                        )}
                                    </TableCell>
                                    {!stacked && (
                                        <TableCell valign="top" align="right">
                                            <QuillRecommendationResolutionButtons recommendation={row} />
                                        </TableCell>
                                    )}
                                </TableRow>
                                {isExpanded && (
                                    <TableRow>
                                        <TableCell colSpan={stacked ? 3 : 4} className="whitespace-normal">
                                            <QuillRecommendationSteps steps={row.steps ?? []} rule={row.rule} />
                                        </TableCell>
                                    </TableRow>
                                )}
                            </Fragment>
                        )
                    })}
                </TableBody>
            </Table>
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={RECOMMENDATIONS_PAGE_SIZE}
                    total={rows.length}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
