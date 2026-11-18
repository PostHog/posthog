import { useActions, useValues } from 'kea'

import { IconBolt, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, LemonTag } from '@posthog/lemon-ui'

import { IconArrowDown } from 'lib/lemon-ui/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { ScannerSelfDrivingStatsApi, SelfDrivingPullRequestApi } from '../../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerSelfDrivingStatsLogic } from '../scannerSelfDrivingStatsLogic'

// Each stage is narrower than the one above it, so the four read as a funnel.
const STAGE_WIDTHS = ['w-full', 'w-11/12', 'w-5/6', 'w-3/4']

const REPORTS_TOOLTIP =
    'A report can combine signals from several scanners and other sources, so this counts contributions, not sole causes.'

/** `owner/repo#123` for a GitHub pull request URL, or the URL itself for anything else. */
function pullRequestLabel(url: string): string {
    const match = url.match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/)
    return match ? `${match[1]}#${match[2]}` : url
}

function pullRequestItems(pullRequests: SelfDrivingPullRequestApi[]): LemonMenuItem[] {
    return pullRequests.map((pr) => ({
        label: (
            <span className="flex items-center gap-2">
                {pullRequestLabel(pr.url)}
                {pr.merged && (
                    <LemonTag type="completion" size="small">
                        Merged
                    </LemonTag>
                )}
            </span>
        ),
        to: pr.url,
        targetBlank: true,
    }))
}

function CardShell({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary p-4 flex flex-col gap-3" data-attr="vision-self-driving-card">
            <div className="border-b border-primary pb-2">
                <span className="text-sm font-medium">Self-driving</span>
            </div>
            {children}
        </div>
    )
}

function FunnelStage({
    index,
    count,
    label,
    items,
    emptyReason,
    tooltip,
}: {
    index: number
    count: number
    label: string
    items?: LemonMenuItem[]
    emptyReason?: string
    tooltip?: string
}): JSX.Element {
    const content = (
        <span className="flex w-full items-baseline justify-between gap-2">
            <span>{label}</span>
            <span className="font-semibold tabular-nums">{count.toLocaleString()}</span>
        </span>
    )
    return (
        <div className={`${STAGE_WIDTHS[index]} mx-auto`}>
            {items ? (
                <LemonMenu items={items} placement="bottom-end">
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        sideIcon={<IconChevronDown />}
                        tooltip={tooltip}
                        disabledReason={count === 0 ? emptyReason : undefined}
                    >
                        {content}
                    </LemonButton>
                </LemonMenu>
            ) : (
                <div className="border rounded px-2 py-1 text-sm">{content}</div>
            )}
        </div>
    )
}

function FunnelArrow(): JSX.Element {
    return <IconArrowDown className="mx-auto text-muted text-sm" aria-hidden />
}

function Funnel({ stats }: { stats: ScannerSelfDrivingStatsApi }): JSX.Element {
    const reportItems: LemonMenuItem[] = stats.reports.map((report) => ({
        label: report.title || 'Untitled report',
        to: urls.inboxReport('reports', report.id),
    }))
    return (
        <div className="flex flex-col gap-0.5" data-attr="vision-self-driving-funnel">
            <FunnelStage index={0} count={stats.signals_emitted} label="Signals emitted" />
            <FunnelArrow />
            <FunnelStage
                index={1}
                count={stats.reports_contributed}
                label={pluralize(stats.reports_contributed, 'Report', 'Reports', false)}
                items={reportItems}
                emptyReason="No reports include this scanner's signals yet"
                tooltip={REPORTS_TOOLTIP}
            />
            <FunnelArrow />
            <FunnelStage
                index={2}
                count={stats.prs_opened}
                label="PRs opened"
                items={pullRequestItems(stats.pull_requests)}
                emptyReason="No pull requests opened yet"
            />
            <FunnelArrow />
            <FunnelStage
                index={3}
                count={stats.prs_merged}
                label="PRs merged"
                items={pullRequestItems(stats.pull_requests.filter((pr) => pr.merged))}
                emptyReason="No pull requests merged yet"
            />
        </div>
    )
}

export function ScannerSelfDrivingCard({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner, turningOnSelfDriving } = useValues(replayScannerLogic({ id: scannerId }))
    const { turnOnSelfDriving } = useActions(replayScannerLogic({ id: scannerId }))
    const { selfDrivingStats, selfDrivingStatsLoading } = useValues(scannerSelfDrivingStatsLogic({ scannerId }))

    // Unresolved data renders as loading, never as the off state or the empty state.
    if (!scanner || (selfDrivingStatsLoading && !selfDrivingStats)) {
        return (
            <CardShell>
                <LemonSkeleton className="h-24 w-full" />
            </CardShell>
        )
    }
    const on = scanner.emits_signals
    // Signals sent before self-driving was turned off still count, so the off copy only
    // replaces the funnel when there is nothing to show.
    if (!on && (!selfDrivingStats || selfDrivingStats.signals_emitted === 0)) {
        return (
            <CardShell>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">
                        Send this scanner's findings to Signals, where agents investigate them and open pull requests.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconBolt />}
                        onClick={() => turnOnSelfDriving()}
                        loading={turningOnSelfDriving}
                        disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level) ?? undefined}
                        data-attr="vision-self-driving-turn-on"
                    >
                        Turn on self-driving
                    </LemonButton>
                </div>
            </CardShell>
        )
    }
    if (!selfDrivingStats) {
        return (
            <CardShell>
                <div className="text-sm text-muted">Couldn't load what self-driving did with this scanner.</div>
            </CardShell>
        )
    }
    if (selfDrivingStats.signals_emitted === 0) {
        return (
            <CardShell>
                <div className="text-sm text-muted">
                    No signals yet. Findings go to Signals as sessions are scanned.
                </div>
            </CardShell>
        )
    }
    return (
        <CardShell>
            <Funnel stats={selfDrivingStats} />
        </CardShell>
    )
}
