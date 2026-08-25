import { useActions, useValues } from 'kea'

import { Tooltip as LemonTooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Button, Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { PropertyOperator } from '~/types'

import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { IssueRelease, ReleaseBucketing, formatReleaseVersion } from './issueReleases'
import { IssueReleaseStrip } from './IssueReleaseStrip'

export type IssueReleaseRowKind = 'release' | 'other' | 'unattributed'

interface IssueReleaseRowProps {
    release: IssueRelease
    kind: IssueReleaseRowKind
    label: string
    color: string
    bucketing: ReleaseBucketing
    maxValue: number
    total: number
}

export function IssueReleaseRow({
    release,
    kind,
    label,
    color,
    bucketing,
    maxValue,
    total,
}: IssueReleaseRowProps): JSX.Element {
    const { applyPropertyFilter } = useActions(issueFilterPreviewLogic)
    const { timezone } = useValues(teamLogic)
    const share = total > 0 ? release.total / total : 0
    const filterable = kind !== 'other'

    const formatBucket = (index: number): string =>
        dayjs(bucketing.bucketStarts[index] * 1000)
            .tz(timezone)
            .format('D MMM YYYY HH:mm')

    const onSelect = (): void => {
        if (kind === 'unattributed') {
            applyPropertyFilter('$app_version', null, PropertyOperator.IsNotSet, true)
        } else {
            applyPropertyFilter('$app_version', release.version, PropertyOperator.Exact, true)
        }
    }

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
                        <span className="font-semibold">{formatReleaseVersion(release)}</span>
                        {kind === 'release' && <span>{release.namespace ?? 'No app namespace'}</span>}
                        {release.firstSeenIndex >= 0 && (
                            <span>
                                {formatBucket(release.firstSeenIndex)} to {formatBucket(release.lastSeenIndex)}
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
                release={release}
                label={label}
                color={color}
                bucketing={bucketing}
                maxValue={maxValue}
            />
            <div className="flex items-baseline justify-end gap-1 tabular-nums">
                <Text size="xs" weight="semibold">
                    {humanFriendlyLargeNumber(release.total)}
                </Text>
                <Text size="xxs" variant="muted">
                    {Math.round(share * 100)}%
                </Text>
            </div>
        </div>
    )
}
