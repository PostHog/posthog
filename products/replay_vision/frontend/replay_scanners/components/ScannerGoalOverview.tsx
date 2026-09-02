import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonSnack, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerEditorStep, scannerStepUrlWithParams } from '../scannerEditorSceneLogic'
import { OBSERVATION_CREDITS_BY_MODEL, SCANNER_TYPE_TAG_TYPE, modelName, scannerTypeLabel } from '../types'

/** Why the draft chose this model, doubling as the guidance on when each tier fits. Keyed by the
 * concrete model id so a retired model just falls through to the generic line. */
function modelRoleLabel(model: string): string {
    if (model === 'gemini-3.5-flash-lite') {
        return 'Cheapest tier. Best for simple yes/no checks.'
    }
    if (model === 'gemini-3.7-flash') {
        return 'Most capable tier. Best for nuanced scoring or summaries.'
    }
    if (model === 'gemini-3-flash-preview') {
        return 'Balanced tier. A good default for everyday scanners.'
    }
    return 'Change the model on the Configure step to trade cost for capability.'
}

/** The activity-filter badge label for each quality mode: how much of the eligible pool it keeps by
 * how eventful each recording is. */
function activityFilterLabel(mode: string): string {
    if (mode === 'balanced') {
        return 'Skip least active'
    }
    if (mode === 'focused') {
        return 'Only most active'
    }
    return 'All recordings'
}

/** One label:value row in the sampling and budget block. */
function StatRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <>
            <span className="text-muted">{label}</span>
            <span>{children}</span>
        </>
    )
}

function OverviewSection({
    label,
    info,
    editStep,
    scannerId,
    children,
}: {
    label: string
    /** Tooltip on an info icon beside the label, for a caveat the numbers below need. */
    info?: string
    editStep?: ScannerEditorStep
    scannerId: string
    children: React.ReactNode
}): JSX.Element {
    const { searchParams } = useValues(router)
    return (
        <div className="bg-bg-light border rounded-lg p-4 flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0 space-y-2">
                <div className="flex items-center gap-1 text-xs text-tertiary uppercase tracking-wide">
                    <span>{label}</span>
                    {info ? (
                        <Tooltip title={info}>
                            <IconInfo className="text-sm" />
                        </Tooltip>
                    ) : null}
                </div>
                {children}
            </div>
            {editStep ? (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() =>
                        router.actions.push(
                            scannerStepUrlWithParams(editStep, scannerId, { ...searchParams, from: 'overview' })
                        )
                    }
                    data-attr={`vision-goal-overview-edit-${editStep}`}
                >
                    Edit
                </LemonButton>
            ) : null}
        </div>
    )
}

/** The landing step after a goal-based draft: the whole drafted config, ordered by comprehension,
 * with each section deep-linking into the wizard step that edits it. */
export function ScannerGoalOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId })
    const {
        scanner,
        goalDraft,
        goalDraftLoading,
        goalBudgetInput,
        scannerEstimate,
        scannerEstimateLoading,
        isScannerSubmitting,
    } = useValues(logic)
    const { submitScanner, loadScannerEstimate } = useActions(logic)

    useEffect(() => {
        // On a reload the in-memory draft is gone but the form was restored, so count what it holds.
        // On the live path the draft-success listener already triggered the count.
        if (!goalDraftLoading && !goalDraft) {
            loadScannerEstimate()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const firstProperty = scanner.query?.properties?.[0]
    const pageValues =
        firstProperty &&
        'value' in firstProperty &&
        Array.isArray(firstProperty.value) &&
        firstProperty.value.length > 0
            ? firstProperty.value
            : null

    const eventValues =
        scanner.query && 'events' in scanner.query && Array.isArray(scanner.query.events)
            ? scanner.query.events.map((e) => String(e.name ?? e.id)).filter(Boolean)
            : []

    // The draft is still generating: show the page's shape so the wait reads as progress.
    if (goalDraftLoading) {
        return <ScannerGoalOverviewSkeleton />
    }

    const zeroMatches = scannerEstimate !== null && scannerEstimate.matched_sessions_in_window === 0
    // Read the projection and credits from the live estimate, not the in-memory draft: the estimate
    // is loaded on this page, priced at the form's model and rate, and survives a reload; the draft
    // fields do not. It also matches the eligible count above, since both come from one estimate.
    const monthlyObservations = scannerEstimate?.estimated_observations_per_month ?? null
    const monthlyCredits = scannerEstimate?.estimated_credits_per_month ?? null
    const samplingPct = Math.round(scanner.sampling_rate * 100)
    const creditsPerObservation =
        scannerEstimate?.credits_per_observation ?? OBSERVATION_CREDITS_BY_MODEL[scanner.model] ?? null
    // The budget is credits, so compare the projected credit cost against the cap (which the draft
    // set to the stated budget). The rate cannot go below the minimum, so a budget under that floor
    // projects above it.
    const budgetCredits = scanner.credit_limit ?? goalBudgetInput
    const overBudget = monthlyCredits != null && budgetCredits != null && monthlyCredits > budgetCredits

    const saveDisabledReason =
        getReplayVisionEditDisabledReason(scanner.user_access_level) ??
        (zeroMatches ? 'No recordings are eligible. Change the filter first.' : undefined)

    return (
        <div className="flex flex-col gap-3">
            <OverviewSection label="What it understood" scannerId={scannerId}>
                <div className="text-sm">{goalDraft?.rationale?.trim() || scanner.description}</div>
            </OverviewSection>

            <OverviewSection label="Name" editStep="details" scannerId={scannerId}>
                <div className="text-sm font-medium">{scanner.name}</div>
                {scanner.description ? <div className="text-sm text-muted">{scanner.description}</div> : null}
            </OverviewSection>

            <OverviewSection label="What it will ask" editStep="configure" scannerId={scannerId}>
                <div className="space-y-3">
                    <LemonTag type={SCANNER_TYPE_TAG_TYPE[scanner.scanner_type]}>
                        {scannerTypeLabel(scanner.scanner_type)}
                    </LemonTag>
                    <div className="text-sm whitespace-pre-wrap">{scanner.scanner_config.prompt}</div>
                    <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-sm border-t pt-3">
                        <StatRow label="Model">
                            <span className="inline-flex items-center gap-2">
                                <LemonTag type="muted">{modelName(scanner.model)}</LemonTag>
                                {creditsPerObservation != null ? (
                                    <span className="text-muted">
                                        {formatCreditCount(creditsPerObservation)} / observation
                                    </span>
                                ) : null}
                            </span>
                        </StatRow>
                    </div>
                    <div className="text-xs text-muted">{modelRoleLabel(scanner.model)}</div>
                </div>
            </OverviewSection>

            <OverviewSection label="Eligible recordings" editStep="triggers" scannerId={scannerId}>
                {pageValues || eventValues.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                        {(pageValues ?? []).map((page) => (
                            <LemonSnack key={`page-${String(page)}`}>{String(page)}</LemonSnack>
                        ))}
                        {eventValues.map((event) => (
                            <LemonSnack key={`event-${event}`}>{event}</LemonSnack>
                        ))}
                    </div>
                ) : (
                    <div className="text-sm">Every recording (no filter)</div>
                )}
                {scannerEstimateLoading ? (
                    <div className="flex items-center gap-2 text-sm text-muted">
                        <Spinner />
                        <span>Counting eligible recordings…</span>
                    </div>
                ) : zeroMatches ? (
                    <LemonBanner type="warning">
                        No recordings match these filters for the last {pluralize(scannerEstimate.window_days, 'day')}.
                        Change the filter, or the scanner may never run.
                    </LemonBanner>
                ) : scannerEstimate ? (
                    <div className="text-sm text-muted">
                        {scannerEstimate.matched_sessions_in_window.toLocaleString()} in the last{' '}
                        {pluralize(scannerEstimate.window_days, 'day')}
                    </div>
                ) : null}
            </OverviewSection>

            <OverviewSection
                label="Sampling and budget"
                info="Estimated from your last 7 days of recordings, projected to a month. Your real volume follows your future traffic, so treat this as a guide."
                editStep="budget"
                scannerId={scannerId}
            >
                <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-sm">
                    <StatRow label="Goal">
                        {monthlyObservations != null ? (
                            <span className="font-medium">
                                about {monthlyObservations.toLocaleString()} recordings a month
                            </span>
                        ) : scannerEstimateLoading ? (
                            <Spinner />
                        ) : (
                            <span className="text-muted">Not available</span>
                        )}
                    </StatRow>
                    <StatRow label="Sampling">
                        <LemonTag type="muted">{samplingPct}%</LemonTag>
                    </StatRow>
                    <StatRow label="Activity filter">
                        <LemonTag type="muted">{activityFilterLabel(scanner.sampling_mode)}</LemonTag>
                    </StatRow>
                    <StatRow label="Cost estimate">
                        {monthlyCredits != null ? (
                            <span>
                                about {formatCreditCount(monthlyCredits)} a month (≈ {creditsToUsd(monthlyCredits)})
                            </span>
                        ) : scannerEstimateLoading ? (
                            <Spinner />
                        ) : (
                            <span className="text-muted">Not available</span>
                        )}
                    </StatRow>
                    {scanner.credit_limit != null ? (
                        <StatRow label="Monthly cap">
                            <span className="text-muted">{formatCreditCount(scanner.credit_limit)}</span>
                        </StatRow>
                    ) : null}
                </div>
                {overBudget ? (
                    <LemonBanner type="warning">
                        This is already at the lowest sampling rate, so it will watch about{' '}
                        {monthlyObservations?.toLocaleString()} recordings a month, more than your budget covers. To
                        watch fewer, narrow which recordings are eligible above, for example by device type or country.
                    </LemonBanner>
                ) : null}
            </OverviewSection>

            <div className="flex items-center justify-end gap-2">
                <LemonButton
                    type="secondary"
                    onClick={() => router.actions.push(urls.replayVisionScannerTemplate('new'))}
                    data-attr="vision-goal-overview-start-over"
                >
                    Start over
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => submitScanner()}
                    loading={isScannerSubmitting}
                    disabledReason={saveDisabledReason}
                    data-attr="vision-goal-overview-create"
                >
                    Create scanner
                </LemonButton>
            </div>
        </div>
    )
}

/** The overview's shape while the draft is still generating, so navigating there reads as progress. */
function ScannerGoalOverviewSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {['What it understood', 'Name', 'What it will ask', 'Eligible recordings', 'Sampling and budget'].map(
                (label) => (
                    <div key={label} className="bg-bg-light border rounded-lg p-4 space-y-2">
                        <div className="text-xs text-tertiary uppercase tracking-wide">{label}</div>
                        <LemonSkeleton className="h-4 w-3/4" />
                        <LemonSkeleton className="h-4 w-1/2" />
                    </div>
                )
            )}
        </div>
    )
}
