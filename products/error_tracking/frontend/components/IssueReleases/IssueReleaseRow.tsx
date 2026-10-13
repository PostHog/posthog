import { useValues } from 'kea'

import { Tooltip as LemonTooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Button, Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { IssueReleaseStrip as IssueReleaseStripData } from './issueReleases'
import { IssueReleaseStrip } from './IssueReleaseStrip'

interface IssueReleaseRowProps {
    strip: IssueReleaseStripData
    buckets: string[]
    maxValue: number
    total: number
    onSelect: () => void
}

export function IssueReleaseRow({ strip, buckets, maxValue, total, onSelect }: IssueReleaseRowProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const { series, kind, label, color } = strip
    const share = total > 0 ? series.total / total : 0
    const filterable = kind !== 'other'

    const formatDate = (iso: string): string => dayjs(iso).tz(timezone).format('D MMM YYYY HH:mm')

    const swatch = (
        // eslint-disable-next-line react/forbid-dom-props
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
    )

    return (
        <div className="grid h-7 grid-cols-[minmax(0,8rem)_minmax(0,1fr)_4.5rem] items-center gap-x-2">
            <LemonTooltip
                delayMs={0}
                placement="right"
                title={
                    <div className="flex flex-col gap-0.5">
                        <span className="font-semibold">{label}</span>
                        {strip.release && <span>{strip.release.namespace ?? 'No app namespace'}</span>}
                        {series.first_seen && series.last_seen && (
                            <span>
                                {formatDate(series.first_seen)} to {formatDate(series.last_seen)}
                            </span>
                        )}
                        {filterable && <span className="text-muted-alt">Click to filter exceptions</span>}
                    </div>
                }
            >
                {filterable ? (
                    <Button
                        variant="default"
                        size="sm"
                        className="h-6 w-full min-w-0 justify-start gap-1.5 px-1.5 text-xs"
                        data-attr="error-tracking-issue-release-filter"
                        onClick={onSelect}
                    >
                        {swatch}
                        <span className={kind === 'unattributed' ? 'truncate text-muted-foreground' : 'truncate'}>
                            {label}
                        </span>
                    </Button>
                ) : (
                    <div className="flex h-6 min-w-0 items-center gap-1.5 px-1.5">
                        {swatch}
                        <Text size="xs" variant="muted" className="truncate">
                            {label}
                        </Text>
                    </div>
                )}
            </LemonTooltip>
            <IssueReleaseStrip
                stripKey={strip.key}
                label={label}
                color={color}
                counts={series.counts}
                buckets={buckets}
                maxValue={maxValue}
            />
            <div className="flex items-baseline justify-end gap-1 tabular-nums">
                <Text size="xs" weight="semibold">
                    {humanFriendlyLargeNumber(series.total)}
                </Text>
                <Text size="xxs" variant="muted">
                    {share > 0 && share < 0.005 ? '<1%' : `${Math.round(share * 100)}%`}
                </Text>
            </div>
        </div>
    )
}
