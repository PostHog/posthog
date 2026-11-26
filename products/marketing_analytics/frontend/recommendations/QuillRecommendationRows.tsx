import { Fragment } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Badge, Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { formatMarketingMoney } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsRecommendation } from '~/queries/schema/schema-general'

import { QuillRecommendationCpa } from './QuillRecommendationCpa'
import { QUILL_DIRECTION_BADGE } from './QuillRecommendationImpactTotals'
import { QuillRecommendationResolutionButtons } from './QuillRecommendationResolutionButtons'
import { QuillRecommendationSteps } from './QuillRecommendationSteps'
import { IMPACT_DIRECTION_LABELS, isResolved } from './recommendations'

export function QuillRecommendationRows({
    rows,
    expanded,
    onToggle,
}: {
    rows: MarketingAnalyticsRecommendation[]
    expanded: Set<string>
    onToggle: (key: string, rule: MarketingAnalyticsRecommendation['rule']) => void
}): JSX.Element {
    return (
        <Table fullWidth size="sm">
            <TableHeader>
                <TableRow>
                    <TableHead>For</TableHead>
                    <TableHead expand>Recommendation</TableHead>
                    <TableHead align="right">Impact</TableHead>
                    <TableHead />
                </TableRow>
            </TableHeader>
            <TableBody>
                {rows.map((row) => {
                    const hasSteps = !!row.steps?.length
                    const isExpanded = hasSteps && expanded.has(row.key)
                    return (
                        <Fragment key={row.key}>
                            <TableRow
                                // Dims the content but not the last cell, so Restore still reads as a live button.
                                className={isResolved(row) ? '[&>td:not(:last-child)]:opacity-60' : undefined}
                            >
                                <TableCell valign="top" className="w-1/4 min-w-40 whitespace-normal break-words">
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
                                                {isExpanded ? 'Hide instructions' : 'View instructions'}
                                                {isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                            </Button>
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
                                <TableCell valign="top" align="right">
                                    <QuillRecommendationResolutionButtons recommendation={row} />
                                </TableCell>
                            </TableRow>
                            {isExpanded && (
                                <TableRow>
                                    <TableCell colSpan={4} className="whitespace-normal">
                                        <QuillRecommendationSteps steps={row.steps ?? []} rule={row.rule} />
                                    </TableCell>
                                </TableRow>
                            )}
                        </Fragment>
                    )
                })}
            </TableBody>
        </Table>
    )
}
