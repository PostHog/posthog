import './ScannerSummary.scss'

import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab } from '../replayScannerSceneLogic'
import { scannerScoutLogic } from '../scannerScoutLogic'
import { ClippedPreview } from './ClippedPreview'
import { ScannerScoutReportModal } from './ScannerScoutReportModal'

function CardShell({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="border rounded bg-surface-primary p-4 flex flex-col gap-2 min-h-38"
            data-attr="vision-scanner-scout-card"
        >
            {children}
        </div>
    )
}

function CardHeader({ meta, actions }: { meta?: React.ReactNode; actions?: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-2 border-b border-primary pb-2">
            <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium">Latest scout report</span>
                {meta && <span className="text-xs text-muted">{meta}</span>}
            </div>
            {actions && <div className="flex items-center gap-1">{actions}</div>}
        </div>
    )
}

// The scanner page's hero: what this scanner's scouts most recently reported. Shows the latest
// report when one exists, otherwise the state that gets the user there (add one / paused / quiet).
export function ScannerScoutCard({
    scannerId,
    scannerName,
}: {
    scannerId: string
    scannerName: string
}): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const {
        scoutConfigs,
        scoutConfigsLoading,
        scoutReportsLoading,
        scoutReportsFailed,
        scoutConfigsForScanner,
        latestReportRow,
        latestRun,
        runningRun,
        manualRunScoutIds,
        enrolled,
    } = useValues(logic)
    const { runScoutNow, loadScoutConfigs, loadScoutReports, openReport } = useActions(logic)

    // Running a scout spends credits and pausing one changes what the scanner watches, so every
    // mutating control here sits behind the scanner's own edit bar, like the digest and alert flows.
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)
    // Same bar as the Scouts tab, plus skill editing: a scout reads this scanner's observations.
    const createDisabledReason =
        editDisabledReason ??
        getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor)
    const scoutsTabUrl = combineUrl(urls.replayVision(scannerId), { tab: ReplayScannerTab.Scouts }).url

    if (scoutConfigs === null) {
        if (scoutConfigsLoading) {
            // Holds the card's place at the height of its common no-scout row, so the overview below doesn't jump when the configs arrive.
            return (
                <CardShell>
                    <CardHeader />
                    <LemonSkeleton className="h-8 w-full" />
                </CardShell>
            )
        }
        return (
            <CardShell>
                <CardHeader />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">Couldn't load this scanner's scouts.</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => loadScoutConfigs()}
                        data-attr="vision-scanner-scout-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            </CardShell>
        )
    }

    if (scoutConfigsForScanner.length === 0) {
        return (
            <CardShell>
                <CardHeader />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">
                        Add a scout to get a daily agent-written digest of what this scanner finds, here and in your
                        inbox.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlus />}
                        to={scoutsTabUrl}
                        disabledReason={createDisabledReason ?? undefined}
                        data-attr="vision-scanner-scout-create"
                    >
                        Add a scout
                    </LemonButton>
                </div>
            </CardShell>
        )
    }

    const single = scoutConfigsForScanner.length === 1 ? scoutConfigsForScanner[0] : null
    const allPaused = scoutConfigsForScanner.every((config) => !config.enabled)
    const runDisabledReason = editDisabledReason ?? (runningRun ? 'A scout run is already in progress' : undefined)

    return (
        <CardShell>
            <CardHeader
                meta={
                    <>
                        {scoutConfigsForScanner.length > 1 && `${scoutConfigsForScanner.length} scouts`}
                        {scoutConfigsForScanner.length > 1 && latestReportRow && ' · '}
                        {latestReportRow && (
                            <TZLabel time={latestReportRow.filed_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                        )}
                    </>
                }
                actions={
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        to={scoutsTabUrl}
                        data-attr="vision-scanner-scout-manage"
                    >
                        Manage scouts
                    </LemonButton>
                }
            />
            {enrolled === false && (
                <LemonBanner type="warning" className="text-sm">
                    Scouts aren't enabled for this project yet, so this scanner's scouts won't run automatically.
                </LemonBanner>
            )}
            {!latestReportRow && scoutReportsLoading ? (
                // "Nothing reported yet" is a verdict about reports that have arrived. The configs
                // land before the reports do, so without this the card states that verdict on every
                // cold load, then replaces it once the reports resolve.
                <LemonSkeleton className="h-16 w-full" />
            ) : !latestReportRow && scoutReportsFailed ? (
                // A failed load is not a quiet scanner, and Run now below spends credits.
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">Couldn't load this scanner's reports.</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => loadScoutReports()}
                        data-attr="vision-scanner-scout-reports-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            ) : latestReportRow ? (
                // Boxed like the Configuration card's prompt. Agent-written content derived from recordings:
                // render non-PostHog images as links, not auto-fetched <img>s.
                <div className="bg-surface-secondary border rounded p-2">
                    <ClippedPreview
                        clip="tall"
                        buttonLabel="Show full report"
                        onOpenFull={() => openReport(latestReportRow.report_id)}
                        dataAttr="vision-scanner-scout-expand"
                    >
                        <LemonMarkdown className="ScannerSummaryMarkdown text-sm" disableImages>
                            {latestReportRow.summary || latestReportRow.title || ''}
                        </LemonMarkdown>
                    </ClippedPreview>
                </div>
            ) : (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">
                        {allPaused ? (
                            single ? (
                                'This scout is paused, so it files nothing until you resume it.'
                            ) : (
                                'Every scout on this scanner is paused, so they file nothing until you resume them.'
                            )
                        ) : latestRun ? (
                            <>
                                Last checked <TZLabel time={latestRun.created_at} />. Nothing reported yet.
                            </>
                        ) : (
                            'No reports yet. The first one arrives after the next scheduled run.'
                        )}
                    </span>
                    {single && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => runScoutNow(single.id)}
                            loading={manualRunScoutIds.includes(single.id)}
                            disabledReason={runDisabledReason}
                            data-attr="vision-scanner-scout-run-now"
                        >
                            {runningRun ? 'Running…' : 'Run now'}
                        </LemonButton>
                    )}
                </div>
            )}
            <ScannerScoutReportModal scannerId={scannerId} scannerName={scannerName} />
        </CardShell>
    )
}
