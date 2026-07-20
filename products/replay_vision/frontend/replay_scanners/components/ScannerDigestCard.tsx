import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { scannerDigestLogic } from '../scannerDigestLogic'

function EditorGate({ children }: { children: JSX.Element }): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.SessionRecording}
            minAccessLevel={AccessControlLevel.Editor}
        >
            {children}
        </AccessControlAction>
    )
}

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
    const { digest, latestRun, latestRunLoading, digestCreating, expanded, visionActionsLoading } = useValues(logic)
    const { createDigest, toggleExpanded, toggleActionEnabled } = useActions(logic)

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
                    <EditorGate>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={createDigest}
                            loading={digestCreating}
                            data-attr="vision-scanner-digest-create"
                        >
                            Turn on daily digest
                        </LemonButton>
                    </EditorGate>
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
                    <EditorGate>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => toggleActionEnabled(digest.id)}
                            data-attr="vision-scanner-digest-resume"
                        >
                            Resume
                        </LemonButton>
                    </EditorGate>
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
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.replayVisionActionEdit(digest.id)}
                        data-attr="vision-scanner-digest-edit"
                    >
                        Edit schedule
                    </LemonButton>
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
            <div className={expanded ? undefined : 'max-h-60 overflow-hidden'}>
                {/* LLM/replay-derived content: render non-PostHog images as links, not auto-fetched <img>s. */}
                <LemonMarkdown className="text-sm" disableImages>
                    {latestRun.synthesized_markdown}
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
