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
    if (row.platform !== 'GoogleAds') {
        return <span className="text-muted">–</span>
    }
    return (
        <div className="flex flex-col items-end gap-1">
            {(
                [
                    ['topImpressionRate', 'Top', 'Percentage of Google Search ad impressions shown among the top ads.'],
                    [
                        'absoluteTopImpressionRate',
                        'First',
                        'Percentage of Google Search ad impressions shown as the first ad.',
                    ],
                ] as const
            ).map(([metric, label, definition]) => (
                <div key={metric} className="flex max-w-full flex-wrap items-center justify-end gap-x-1">
                    <Tooltip title={`${definition} Excludes Search partners. Requires a sync with ad placement data.`}>
                        <span className="text-xs text-secondary">{label}</span>
                    </Tooltip>
                    <ChangeValueCell
                        value={row[metric] == null ? null : [row[metric], row.previous?.[metric] ?? null]}
                        compare={compare}
                        kind="percentage"
                        currency={CurrencyCode.USD}
                        tooltipContent={`${definition} Excludes Search partners.`}
                    />
                </div>
            ))}
        </div>
    )
}
