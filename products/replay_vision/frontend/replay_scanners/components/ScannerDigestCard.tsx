import './ScannerSummary.scss'

import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerDigestLogic } from '../scannerDigestLogic'
import { resolveObservationCitations } from '../visionActionRunSceneLogic'

function CardShell({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="border rounded p-4 flex flex-col gap-2" data-attr="vision-scanner-digest-card">
            {children}
        </div>
    )
}

function CardHeader({ meta }: { meta?: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium">Daily digest</span>
            {meta && <span className="text-xs text-muted">{meta}</span>}
        </div>
    )
}

// The scanner page's hero: the built-in daily digest. Shows the latest summary when one exists,
// otherwise the state that gets the user there (turn on / paused / first run pending).
export function ScannerDigestCard({
    scannerId,
    scannerName,
}: {
    scannerId: string
    scannerName: string
}): JSX.Element | null {
    const logic = scannerDigestLogic({ scannerId, scannerName })
    const {
        digest,
        latestRun,
        latestRunLoading,
        digestCreating,
        expanded,
        visionActionsLoading,
        runningNow,
        runInProgress,
    } = useValues(logic)
    const { createDigest, toggleExpanded, toggleActionEnabled, runNow } = useActions(logic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)
    // Disable Run now while a run is actually processing (not just during the trigger request). A
    // second run coalesces server-side anyway, but disabling makes that obvious and stops spam clicks.
    const runNowDisabledReason = editDisabledReason ?? (runInProgress ? 'A run is already in progress' : undefined)

    if (visionActionsLoading && !digest) {
        return null
    }

    if (!digest) {
        return (
            <CardShell>
                <CardHeader />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">
                        Get a daily AI summary of what this scanner finds, right here.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={createDigest}
                        loading={digestCreating}
                        disabledReason={editDisabledReason}
                        data-attr="vision-scanner-digest-create"
                    >
                        Turn on daily digest
                    </LemonButton>
                </div>
            </CardShell>
        )
    }

    if (!digest.enabled) {
        return (
            <CardShell>
                <CardHeader />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">The daily digest is paused.</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => toggleActionEnabled(digest.id)}
                        disabledReason={editDisabledReason}
                        data-attr="vision-scanner-digest-resume"
                    >
                        Resume
                    </LemonButton>
                </div>
            </CardShell>
        )
    }

    if (!latestRun) {
        if (latestRunLoading) {
            return null
        }
        return (
            <CardShell>
                <CardHeader />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-muted">
                        Nothing summarized yet.
                        {digest.next_run_at && (
                            <>
                                {' '}
                                The next digest arrives{' '}
                                <TZLabel time={digest.next_run_at} formatDate="MMM D, YYYY" formatTime="HH:mm" />.
                            </>
                        )}
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={runNow}
                            loading={runningNow}
                            disabledReason={runNowDisabledReason}
                            data-attr="vision-scanner-digest-run-now-empty"
                        >
                            {runInProgress ? 'Running…' : 'Run now'}
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.replayVisionActionEdit(digest.id)}
                            data-attr="vision-scanner-digest-edit"
                        >
                            Edit schedule
                        </LemonButton>
                    </div>
                </div>
            </CardShell>
        )
    }

    const delivers = (digest.delivery_config?.length ?? 0) > 0

    return (
        <CardShell>
            <CardHeader
                meta={
                    <>
                        <TZLabel
                            time={latestRun.scheduled_at ?? latestRun.created_at}
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                        />
                        {' · '}
                        {latestRun.observation_count} observation{latestRun.observation_count === 1 ? '' : 's'}
                    </>
                }
            />
            {/* The mask's fixed offsets (vs percentages) keep short, unclipped digests fully opaque:
                content under 12rem never reaches the fade band that softens the 15rem (max-h-60) cut. */}
            <div
                className={
                    expanded
                        ? undefined
                        : 'max-h-60 overflow-hidden [mask-image:linear-gradient(to_bottom,black_12rem,transparent_15rem)]'
                }
            >
                {/* LLM/replay-derived content: render non-PostHog images as links, not auto-fetched <img>s.
                    Resolve the summarizer's [obs N] markers into links to each cited observation. */}
                <LemonMarkdown className="ScannerSummaryMarkdown text-sm" disableImages>
                    {resolveObservationCitations(latestRun.synthesized_markdown, latestRun.observations)}
                </LemonMarkdown>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t pt-2">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={toggleExpanded}
                    data-attr="vision-scanner-digest-expand"
                >
                    {expanded ? 'Show less' : 'Show more'}
                </LemonButton>
                <div className="flex-1" />
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={runNow}
                    loading={runningNow}
                    disabledReason={runNowDisabledReason}
                    data-attr="vision-scanner-digest-run-now"
                >
                    {runInProgress ? 'Running…' : 'Run now'}
                </LemonButton>
                {!delivers && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        to={urls.replayVisionActionEdit(digest.id)}
                        data-attr="vision-scanner-digest-slack"
                    >
                        Get this in Slack
                    </LemonButton>
                )}
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={urls.replayVisionAction(digest.id)}
                    data-attr="vision-scanner-digest-history"
                >
                    View history
                </LemonButton>
            </div>
        </CardShell>
    )
}
