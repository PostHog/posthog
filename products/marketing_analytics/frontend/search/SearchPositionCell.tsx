import { Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { CurrencyCode, MarketingAnalyticsSearchRow } from '~/queries/schema/schema-general'

import { ChangeValueCell } from '../dashboard/tables/ChangeValueCell'

export function SearchPositionCell({
    row,
    compare,
}: {
    row: MarketingAnalyticsSearchRow
    compare: boolean
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (row.platform === 'GoogleSearchConsole') {
        return (
            <ChangeValueCell
                value={row.position == null ? null : [row.position, row.previous?.position ?? null]}
                compare={compare}
                kind="decimal"
                currency={CurrencyCode.USD}
                reverseColors
                tooltipContent="Average position in organic Google search, weighted by impressions. Lower is better."
            />
        )
    }
    if (row.platform !== 'GoogleAds' && row.platform !== 'BingAds') {
        return <span className={todayRailNav ? 'text-muted-foreground' : 'text-muted'}>–</span>
    }
    const searchName = row.platform === 'GoogleAds' ? 'Google Search' : 'Microsoft Advertising search'
    const networkNote = row.platform === 'GoogleAds' ? ' Excludes Search partners.' : ''
    return (
        <div className="flex flex-col items-end gap-1">
            {(
                [
                    ['topImpressionRate', 'Top', `Percentage of ${searchName} ad impressions shown among the top ads.`],
                    [
                        'absoluteTopImpressionRate',
                        'First',
                        `Percentage of ${searchName} ad impressions shown as the first ad.`,
                    ],
                ] as const
            ).map(([metric, label, definition]) => {
                const labelTooltip = `${definition}${networkNote} Requires a sync with ad placement data.`
                return (
                    <div
                        key={metric}
                        className={
                            todayRailNav
                                ? 'flex items-center justify-end gap-x-1 whitespace-nowrap *:flex-nowrap'
                                : 'flex max-w-full flex-wrap items-center justify-end gap-x-1'
                        }
                    >
                        {todayRailNav ? (
                            <QuillTooltip>
                                <TooltipTrigger
                                    render={<span className="text-xs text-muted-foreground" tabIndex={0} />}
                                >
                                    {label}
                                </TooltipTrigger>
                                <TooltipContent className="max-w-80">{labelTooltip}</TooltipContent>
                            </QuillTooltip>
                        ) : (
                            <Tooltip title={labelTooltip}>
                                <span className="text-xs text-secondary" tabIndex={0}>
                                    {label}
                                </span>
                            </Tooltip>
                        )}
                        <ChangeValueCell
                            value={row[metric] == null ? null : [row[metric], row.previous?.[metric] ?? null]}
                            compare={compare}
                            kind="percentage"
                            currency={CurrencyCode.USD}
                            tooltipContent={`${definition}${networkNote}`}
                        />
                    </div>
                )
            })}
        </div>
    )
}
