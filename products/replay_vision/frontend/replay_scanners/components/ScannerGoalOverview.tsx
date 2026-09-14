import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'
import { TextMorph } from 'torph/react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonSnack, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { PropertyFilterType } from '~/types'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerEditorStep, scannerStepUrlWithParams } from '../scannerEditorSceneLogic'
import {
    OBSERVATION_CREDITS_BY_MODEL,
    SCANNER_TYPE_TAG_TYPE,
    modelName,
    type ReplayScanner,
    scannerTypeLabel,
} from '../types'

/** Why the draft chose this model, doubling as the guidance on when each tier fits. Keyed by the
 * concrete model id so a retired model just falls through to the generic line. */
function modelRoleLabel(model: string): string {
    if (model === 'gemini-3.5-flash-lite') {
        return 'Cheapest tier. Best for simple yes/no checks.'
    }
    if (model === 'gemini-3.8-flash') {
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

/** One label:value row in the eligible-recordings and sampling blocks. */
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

/** One kind of filter on the drafted scanner, with the values it holds. */
export interface EligibleFilterGroup {
    label: string
    values: string[]
}

/** The targeted experiment and variant, named so the row stands alone before the experiment loads. */
function experimentValues(scanner: ReplayScanner, experimentName?: string): string[] {
    const targeting = scanner.experiment_targeting
    if (!targeting?.experiment_id) {
        return []
    }
    const variant = targeting.variant ? `${targeting.variant} variant` : 'all variants'
    return [`${experimentName ?? `Experiment ${targeting.experiment_id}`} (${variant})`]
}

/** The pages a session must have visited.
 *
 * Read by key, not by position: the properties list can hold a cohort alongside the pages, and
 * taking whichever came first would render a cohort id as a page.
 */
function pageValues(scanner: ReplayScanner): string[] {
    const property = scanner.query?.properties?.find(
        (candidate) => 'key' in candidate && candidate.key === 'visited_page'
    )
    if (!property || !('value' in property) || !Array.isArray(property.value)) {
        return []
    }
    return property.value.map(String)
}

/** The names of the query's events or actions, whichever list is asked for. */
function namedQueryEntities(scanner: ReplayScanner, key: 'events' | 'actions'): string[] {
    const query = scanner.query
    const entities = (query && key in query ? query[key] : null) ?? []
    return entities.map((entity) => String(entity.name ?? entity.id)).filter(Boolean)
}

/** The cohorts the scan is limited to. The query carries only ids, so the name is looked up. */
function cohortValues(scanner: ReplayScanner, cohortNames?: Record<string, string>): string[] {
    return (scanner.query?.properties ?? [])
        .filter((property) => property.type === PropertyFilterType.Cohort)
        .map((property) => String(cohortNames?.[String(property.value)] ?? `Cohort ${property.value}`))
}

/** What the drafted scanner watches, grouped by the kind of filter each value came from.
 *
 * Each kind narrows differently. An experiment picks the people, a page picks where they went, an
 * event or an action picks what they did, and a cohort picks who they are. They also combine, so a
 * flat row of values leaves the reader to guess which value is which kind. The label is also the
 * only thing that makes an action or a cohort readable: neither value says what it is.
 */
export function eligibleFilterGroups(
    scanner: ReplayScanner,
    { experimentName, cohortNames }: { experimentName?: string; cohortNames?: Record<string, string> } = {}
): EligibleFilterGroup[] {
    const kinds: [singular: string, plural: string, values: string[]][] = [
        ['Experiment', 'Experiments', experimentValues(scanner, experimentName)],
        ['Page', 'Pages', pageValues(scanner)],
        ['Event', 'Events', namedQueryEntities(scanner, 'events')],
        ['Action', 'Actions', namedQueryEntities(scanner, 'actions')],
        ['Cohort', 'Cohorts', cohortValues(scanner, cohortNames)],
    ]
    return kinds
        .filter(([, , values]) => values.length > 0)
        .map(([singular, plural, values]) => ({
            label: pluralize(values.length, singular, plural, false),
            values,
        }))
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
        experimentContext,
    } = useValues(logic)
    // Names the drafted cohort, which the query carries only by id.
    const { cohortsById } = useValues(cohortsModel)
    const { submitScanner, loadScannerEstimate } = useActions(logic)

    useEffect(() => {
        // On a reload the in-memory draft is gone but the form was restored, so count what it holds.
        // On the live path the draft-success listener already triggered the count.
        if (!goalDraftLoading && !goalDraft) {
            loadScannerEstimate()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const filterGroups = eligibleFilterGroups(scanner, {
        experimentName: experimentContext?.experiment.name,
        cohortNames: Object.fromEntries(
            Object.entries(cohortsById).map(([id, cohort]) => [id, cohort?.name ?? `Cohort ${id}`])
        ),
    })

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
                {filterGroups.length > 0 ? (
                    <div className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1 text-sm">
                        {filterGroups.map((group) => (
                            <StatRow key={group.label} label={group.label}>
                                <span className="flex flex-wrap gap-1">
                                    {group.values.map((value) => (
                                        <LemonSnack key={value}>{value}</LemonSnack>
                                    ))}
                                </span>
                            </StatRow>
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

// Drafting a scanner runs a model call that takes several seconds, so the wait needs to read as
// work in progress. These rotate above the skeleton, in the same spirit as the insights loader.
const DRAFT_LOADING_MESSAGES = [
    'Reading your goal…',
    'Snuffling through your pages for a match…',
    'Counting hedgehogs and recordings…',
    'Weighing the budget against the traffic…',
    'Picking a model for the job…',
    'Drafting the scanner…',
]

const MESSAGE_INTERVAL_MS = 2500

/** The rotating orange loading bar shown while the draft generates. */
function DraftLoadingBar(): JSX.Element {
    const frozen = inStorybook() || inStorybookTestRunner()
    const [messageIndex, setMessageIndex] = useState(() =>
        frozen ? 0 : Math.floor(Math.random() * DRAFT_LOADING_MESSAGES.length)
    )

    useEffect(() => {
        // A frozen index keeps every Storybook snapshot identical.
        if (frozen) {
            return
        }
        const interval = setInterval(() => {
            setMessageIndex((current) => {
                let next = Math.floor(Math.random() * DRAFT_LOADING_MESSAGES.length)
                if (next === current) {
                    next = (next + 1) % DRAFT_LOADING_MESSAGES.length
                }
                return next
            })
        }, MESSAGE_INTERVAL_MS)
        return () => clearInterval(interval)
    }, [frozen])

    return (
        <div className="flex flex-col items-center gap-1 py-2">
            <TextMorph as="span" className="text-sm font-medium text-secondary">
                {DRAFT_LOADING_MESSAGES[messageIndex]}
            </TextMorph>
            <LoadingBar />
        </div>
    )
}

/** The overview's shape while the draft is still generating, so navigating there reads as progress. */
function ScannerGoalOverviewSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <DraftLoadingBar />
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
