import { useActions, useValues } from 'kea'

import { IconChevronDown, IconDirectedGraph, IconExternal, IconGithub, IconPullRequest } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonTab,
    LemonTabs,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type {
    ReviewDetailApi,
    ReviewDropDispositionEnumApi,
    ReviewDroppedFindingApi,
    ReviewFindingApi,
    ReviewIssuePriorityEnumApi,
    ReviewRecentReviewApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import {
    ReviewHogReviewsListScope,
    ReviewTriggerRequestRunModeEnumApi,
    ReviewTurnDesignEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { AdoptSkillModal } from './AdoptSkillModal'
import { PipelineDetailModal } from './PipelineDetailModal'
import { reviewTitle } from './reviewDisplay'
import { CodeReviewTab, ReviewDrawerTab, reviewHogSettingsLogic } from './reviewHogSettingsLogic'
import { ReviewModeTag } from './ReviewModeTag'
import { ReviewsFilters } from './ReviewsFilters'
import { ReviewsTable } from './ReviewsTable'
import { SectionHeader } from './SectionHeader'
import { DeepArea } from './settings/DeepArea'
import { InboxSection } from './settings/InboxSection'
import { StandardArea } from './settings/StandardArea'
import { prettifySkillName } from './skillNames'

// The Mine tooltip states what the backend's `mine` scope matches: the PR author OR the user who started the run.
const REVIEWS_SCOPE_OPTIONS: {
    value: ReviewHogReviewsListScope
    label: string
    tooltip: string
    'data-attr': string
}[] = [
    {
        value: ReviewHogReviewsListScope.Mine,
        label: 'Mine',
        tooltip: 'Reviews of pull requests you authored, plus reviews you started',
        'data-attr': 'code-review-reviews-scope-mine',
    },
    {
        value: ReviewHogReviewsListScope.Everyone,
        label: 'Everyone',
        tooltip: 'Reviews of every pull request in this project',
        'data-attr': 'code-review-reviews-scope-everyone',
    },
]

/**
 * Scope of the reviews table. It also scopes the proof card and the effectiveness cards on
 * the Settings tab. Skill toggles stay per-user regardless of scope.
 */
function ReviewsScopeFilter(): JSX.Element {
    const { reviewsScope } = useValues(reviewHogSettingsLogic)
    const { setReviewsScope } = useActions(reviewHogSettingsLogic)
    return (
        <LemonSegmentedButton
            size="small"
            value={reviewsScope}
            onChange={(value) => setReviewsScope(value)}
            options={REVIEWS_SCOPE_OPTIONS}
        />
    )
}

function StatsWindowLabel({ reportCount }: { reportCount: number }): JSX.Element {
    const { reviewsScope } = useValues(reviewHogSettingsLogic)
    const scopeOption = REVIEWS_SCOPE_OPTIONS.find((option) => option.value === reviewsScope)
    return (
        <Tooltip title={`${scopeOption?.tooltip}. Set by the Mine / Everyone filter on reviews.`}>
            <span className="text-xxs text-tertiary">
                <span translate="no">{`Last ${reportCount} completed review${reportCount === 1 ? '' : 's'} · ${scopeOption?.label}`}</span>
            </span>
        </Tooltip>
    )
}

/**
 * Proof block: the validation funnel across the in-scope recent reviews, summed from the same
 * stats the effectiveness cards use. Hidden while there are no reviewed findings in scope yet.
 */
function ProofCard(): JSX.Element | null {
    const { perspectiveStats, reviewsScope } = useValues(reviewHogSettingsLogic)
    const everyone = reviewsScope === ReviewHogReviewsListScope.Everyone

    if (perspectiveStats === null) {
        return <LemonSkeleton className="h-24 w-full" />
    }
    const raised = perspectiveStats.perspectives.reduce((sum, p) => sum + p.raised, 0)
    const kept = perspectiveStats.perspectives.reduce((sum, p) => sum + p.kept, 0)
    const dismissed = perspectiveStats.perspectives.reduce((sum, p) => sum + p.dismissed, 0)
    if (raised === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-3xl font-bold tabular-nums text-warning">{kept}</span>
                <span className="text-sm font-semibold">
                    {everyone ? "findings worth the team's time" : 'findings worth your time'}
                </span>
                <span className="text-xs text-secondary">
                    from <span className="font-semibold text-default">{raised}</span> raised ·{' '}
                    <span className="font-semibold text-default">{dismissed}</span> filtered as noise
                </span>
                <span className="ml-auto">
                    <StatsWindowLabel reportCount={perspectiveStats.report_count} />
                </span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-fill-highlight-100">
                <div className="h-full rounded-full bg-warning" style={{ width: `${(kept / raised) * 100}%` }} />
            </div>
            <div className="flex items-center gap-4 text-xs text-tertiary">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block size-2 rounded-full bg-warning" /> Worth your time
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="inline-block size-2 rounded-full bg-border-bold" /> Filtered as noise
                </span>
            </div>
        </LemonCard>
    )
}

/** Where the review pipeline is explained: the full walk-through lives in the Detailed view. */
function PipelineSection(): JSX.Element {
    const { openPipelineDetail } = useActions(reviewHogSettingsLogic)
    return (
        <section className="flex flex-col gap-4">
            <SectionHeader
                icon={<IconDirectedGraph />}
                title="How we review your PRs"
                action={
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openPipelineDetail()}
                        data-attr="review-pipeline-detailed-view"
                    >
                        Detailed view
                    </LemonButton>
                }
            >
                Every review runs through the same steps before it's published, then works through the comment threads
                it leaves open.
            </SectionHeader>
        </section>
    )
}

const PRIORITY_TAG: Record<ReviewIssuePriorityEnumApi, { type: 'danger' | 'warning' | 'muted'; label: string }> = {
    must_fix: { type: 'danger', label: 'Must fix' },
    should_fix: { type: 'warning', label: 'Should fix' },
    consider: { type: 'muted', label: 'Consider' },
}

/** "best_practice" → "Best practice" */
function prettifyCategory(category: string): string {
    const cleaned = category.replace(/_/g, ' ')
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}

// Mirror SINGLE_AGENT_SOURCE and the FlashLens sources in reviewer/constants.py.
const SINGLE_AGENT_MAIN_SOURCE = 'flash-single-agent'
const SINGLE_AGENT_LENS_PREFIX = 'flash-lens-'

/** Scoreboard label for a finding's source skill — blind-spot skills all read as one sweep. */
function perspectiveLabel(skillName: string): string {
    if (skillName.startsWith('review-hog-blind-spots-')) {
        return 'Blind spots'
    }
    if (skillName === SINGLE_AGENT_MAIN_SOURCE) {
        return 'Main review'
    }
    if (skillName.startsWith(SINGLE_AGENT_LENS_PREFIX)) {
        return `Lens: ${prettifySkillName(skillName.slice(SINGLE_AGENT_LENS_PREFIX.length))}`
    }
    if (skillName === 'unknown') {
        return 'Unknown'
    }
    return prettifySkillName(skillName)
}

/** A Standard turn on the single-agent design: no chunks, no perspective selection, no separate validation. */
function isSingleAgentReview(review: ReviewRecentReviewApi | null): boolean {
    return review?.review_design === ReviewTurnDesignEnumApi.SingleAgent
}

/** Lens count from the sessions that ran: one session is the main pass, the rest are lenses. Null when the turn recorded none. */
function singleAgentLensCount(review: ReviewRecentReviewApi): number | null {
    return review.perspective_count ? review.perspective_count - 1 : null
}

/** Posted findings, and how many were raised before drops. Raised is null when unknown or not above posted. */
function singleAgentCounts(review: ReviewRecentReviewApi): { posted: number; raised: number | null } {
    const posted = review.must_fix_count + review.should_fix_count + review.consider_count
    const raised = review.perspective_issue_count
    return { posted, raised: raised !== null && raised > posted ? raised : null }
}

/** The drawer header for a single-agent turn: how it ran, and why the posted count can be lower than the raised count. */
function SingleAgentDrawerSummary({ review }: { review: ReviewDetailApi }): JSX.Element {
    const { setReviewDrawerTab } = useActions(reviewHogSettingsLogic)
    const { posted, raised } = singleAgentCounts(review)
    const lenses = singleAgentLensCount(review)
    const dropped = raised !== null ? raised - posted : 0
    const otherLabel = dropped === 1 ? 'The other one' : `The other ${dropped}`
    return (
        <div className="flex flex-col gap-1 text-sm text-secondary">
            <div>
                Standard review: one main pass over the whole pull request
                {lenses
                    ? ` plus ${lenses} ${lenses === 1 ? 'lens that focuses' : 'lenses that each focus'} on one area`
                    : ''}
                . No separate validation step.
            </div>
            <div>
                {/* A turn whose GitHub publish failed kept its findings without posting them. */}
                {review.turn_published ? 'Posted' : 'Kept'} <span className="font-semibold text-default">{posted}</span>
                {raised !== null ? (
                    <>
                        {' '}
                        of <span className="font-semibold text-default">{raised}</span> issues raised.{' '}
                        {/* Turns that predate the dropped-finding record have nothing to switch to. */}
                        {review.dropped_findings.length ? (
                            <Link onClick={() => setReviewDrawerTab('not_posted')}>{otherLabel}</Link>
                        ) : (
                            otherLabel
                        )}{' '}
                        repeated another finding or comment, {dropped === 1 ? 'was' : 'were'} on code this pull request
                        did not change, or went over the per-review limit.
                    </>
                ) : (
                    ` issue${posted === 1 ? '' : 's'}.`
                )}
            </div>
        </div>
    )
}

function ReviewsSection(): JSX.Element {
    const { reviewsScope } = useValues(reviewHogSettingsLogic)
    return (
        <section className="flex flex-col gap-4">
            <SectionHeader icon={<IconPullRequest />} title="Reviews" action={<ReviewsScopeFilter />}>
                {reviewsScope === ReviewHogReviewsListScope.Everyone
                    ? 'PostHog Review runs on pull requests across this project, latest activity first. Open a review for its findings.'
                    : 'PostHog Review runs on pull requests you authored, plus reviews you started, latest activity first. Open a review for its findings.'}
            </SectionHeader>
            <ProofCard />
            <ReviewsFilters />
            <ReviewsTable />
        </section>
    )
}

/**
 * "Review a pull request": paste any PR URL the project's GitHub App installation can access and
 * start a publishing review, acting as the requesting user. A review resolves the PR's comment
 * threads afterwards when the user's resolve_comments setting is on; the split button's side
 * actions are the per-run variants (review without resolving / resolve only / flash).
 */
function TriggerReviewSection(): JSX.Element {
    const { triggerPrUrl, triggeringReview, triggerUrlResolving, triggerUrlHasFullReview } =
        useValues(reviewHogSettingsLogic)
    const { setTriggerPrUrl, submitTriggerReview } = useActions(reviewHogSettingsLogic)

    const noUrlReason = !triggerPrUrl.trim() ? 'Paste a pull request URL first' : undefined
    // Mirrors the server-side busy-guard for PRs visible in the list; pasted URLs outside it still
    // get the same refusal from the trigger endpoint.
    const resolvingReason = triggerUrlResolving ? 'Still resolving comments from the last review' : undefined
    const inFlightReason = triggeringReview ? 'A run is already starting…' : undefined
    const flashAfterFullReason = triggerUrlHasFullReview
        ? 'This pull request already has a Deep review. Standard does not run after one.'
        : undefined
    return (
        <section className="flex flex-col gap-4">
            <SectionHeader icon={<IconGithub />} title="Review a pull request">
                Start a Deep review of any pull request the GitHub App can access. The review is posted back to the pull
                request and shows up under Reviews below. Your perspectives and other review skills apply to Deep
                reviews only.
            </SectionHeader>
            <form
                className="ml-9 flex flex-wrap items-center gap-2"
                onSubmit={(e) => {
                    e.preventDefault()
                    submitTriggerReview()
                }}
            >
                <LemonInput
                    className="min-w-80 flex-1"
                    placeholder="https://github.com/PostHog/posthog.com/pull/1234"
                    value={triggerPrUrl}
                    onChange={setTriggerPrUrl}
                />
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={triggeringReview}
                    disabledReason={noUrlReason ?? resolvingReason}
                    sideAction={{
                        icon: <IconChevronDown />,
                        disabledReason: noUrlReason ?? resolvingReason ?? inFlightReason,
                        dropdown: {
                            placement: 'bottom-end',
                            overlay: (
                                <>
                                    <LemonButton
                                        fullWidth
                                        onClick={() =>
                                            submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.ReviewOnly)
                                        }
                                        tooltip="Review the pull request but leave its comment threads alone, whatever your setting says."
                                    >
                                        Review without resolving comments
                                    </LemonButton>
                                    <LemonButton
                                        fullWidth
                                        onClick={() =>
                                            submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.ResolveOnly)
                                        }
                                        tooltip="Skip the review and only work through the pull request's existing unresolved comment threads."
                                    >
                                        Only resolve existing comments
                                    </LemonButton>
                                    <LemonButton
                                        fullWidth
                                        onClick={() => submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.Flash)}
                                        tooltip="A lower-cost review that never resolves comments and uses none of your review skills. Its status comment is marked as standard."
                                        disabledReason={flashAfterFullReason}
                                    >
                                        Standard review
                                    </LemonButton>
                                </>
                            ),
                        },
                    }}
                >
                    Review
                </LemonButton>
            </form>
        </section>
    )
}

type FindingSection = 'description' | 'suggestion' | 'validator'

/** A finding that went through the reviewer's own priority and a verdict, unlike a dropped one. */
function isJudgedFinding(finding: ReviewFindingApi | ReviewDroppedFindingApi): finding is ReviewFindingApi {
    return 'validator_note' in finding
}

function FindingCard({
    finding,
    dismissed,
    reason,
}: {
    finding: ReviewFindingApi | ReviewDroppedFindingApi
    dismissed?: boolean
    reason?: JSX.Element
}): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)
    const judged = isJudgedFinding(finding) ? finding : null
    const priority = PRIORITY_TAG[isJudgedFinding(finding) ? finding.effective_priority : finding.priority]
    const location = finding.lines.length
        ? `${finding.file}:${finding.lines.map((r) => (r.end && r.end !== r.start ? `${r.start}–${r.end}` : `${r.start}`)).join(', ')}`
        : finding.file
    const firstRange = finding.lines[0]
    // Deep link to the exact reviewed code: the head SHA pins the lines even after later pushes.
    const githubHref = reviewDetail?.head_sha
        ? `https://github.com/${reviewDetail.repository}/blob/${reviewDetail.head_sha}/${finding.file}` +
          (firstRange
              ? `#L${firstRange.start}${firstRange.end && firstRange.end !== firstRange.start ? `-L${firstRange.end}` : ''}`
              : '')
        : null
    return (
        <div className="flex flex-col gap-2 py-4">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type={dismissed ? 'muted' : priority.type} size="small">
                    {priority.label}
                </LemonTag>
                {judged && judged.effective_priority !== judged.reviewer_priority && (
                    <LemonTag type="muted" size="small">
                        was {PRIORITY_TAG[judged.reviewer_priority].label.toLowerCase()}
                    </LemonTag>
                )}
                {judged?.validator_category && (
                    <LemonTag type="muted" size="small">
                        {prettifyCategory(judged.validator_category)}
                    </LemonTag>
                )}
                {reason}
                {finding.source_perspective && (
                    <span className="text-xs text-tertiary">{perspectiveLabel(finding.source_perspective)}</span>
                )}
            </div>
            <span className={`text-base font-semibold ${dismissed ? 'text-secondary' : ''}`}>{finding.title}</span>
            {githubHref ? (
                <Link
                    to={githubHref}
                    target="_blank"
                    className="self-start font-mono text-xs text-tertiary hover:text-default"
                >
                    {location}
                </Link>
            ) : (
                <span className="font-mono text-xs text-tertiary">{location}</span>
            )}
            {/* Collapsed by default, like the published PR comment — title + location scan, text on demand. */}
            <LemonCollapse<FindingSection>
                multiple
                size="small"
                panels={[
                    {
                        key: 'description',
                        header: 'Description',
                        content: (
                            <LemonMarkdown className="text-sm text-secondary" disableImages>
                                {finding.body}
                            </LemonMarkdown>
                        ),
                    },
                    // A single-agent finding ends its description with the fix, so its suggestion is empty.
                    ...(finding.suggestion
                        ? [
                              {
                                  key: 'suggestion' as const,
                                  header: 'Suggested fix',
                                  content: (
                                      <LemonMarkdown className="text-sm text-secondary" disableImages>
                                          {finding.suggestion}
                                      </LemonMarkdown>
                                  ),
                              },
                          ]
                        : []),
                    // A single-agent turn has no validator, so its note is a placeholder, not reasoning.
                    ...(judged && !isSingleAgentReview(reviewDetail)
                        ? [
                              {
                                  key: 'validator' as const,
                                  header: dismissed ? 'Why it was dismissed' : "Why we think it's a valid issue",
                                  content: (
                                      <LemonMarkdown className="text-sm text-secondary" disableImages>
                                          {judged.validator_note}
                                      </LemonMarkdown>
                                  ),
                              },
                          ]
                        : []),
                ]}
            />
        </div>
    )
}

function DrawerFindingsSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-2.5">
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-24 w-full" />
        </div>
    )
}

/** The "Published" tab: the findings that crossed the urgency threshold, caveated while unpublished. */
function DrawerPublishedTab(): JSX.Element {
    const { reviewFindingsSplit, reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewFindingsSplit) {
        return <DrawerFindingsSkeleton />
    }
    const isPublished = reviewDetail?.published ?? false
    if (!reviewFindingsSplit.published.length && isSingleAgentReview(reviewDetail)) {
        return <div className="text-sm text-secondary">This review found nothing to post to the pull request.</div>
    }
    if (!reviewFindingsSplit.published.length) {
        return (
            <div className="text-sm text-secondary">
                {isPublished
                    ? "Nothing crossed the review's urgency threshold — no comments were posted to the pull request."
                    : "Nothing crossed the review's urgency threshold, and this review hasn't been published to the pull request."}
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            {!isPublished && (
                <p className="m-0 text-xs text-secondary">
                    This review hasn't been published to the pull request yet — these findings crossed the review's
                    urgency threshold, but no comments have been posted.
                </p>
            )}
            <div className="flex flex-col divide-y divide-primary">
                {reviewFindingsSplit.published.map((finding, i) => (
                    <FindingCard key={i} finding={finding} />
                ))}
            </div>
        </div>
    )
}

const DROP_REASON_LABEL: Record<ReviewDropDispositionEnumApi, string> = {
    dedup_sibling: 'Repeat of a finding',
    dedup_comment: 'Already in a PR comment',
    dedup_prior: 'Repeat of an earlier review',
    dedup_anchor: 'Same spot as another finding',
    old_code: 'On unchanged code',
    cap: 'Over the limit',
}

// Display order of the reasons: the label map's key order.
const DROP_REASON_ORDER = Object.keys(DROP_REASON_LABEL) as ReviewDropDispositionEnumApi[]

function DropReason({ finding }: { finding: ReviewDroppedFindingApi }): JSX.Element {
    const label = DROP_REASON_LABEL[finding.disposition]
    return (
        <>
            <LemonTag type="muted" size="small">
                {finding.disposition === 'cap' && finding.rank ? `${label} (#${finding.rank})` : label}
            </LemonTag>
            {finding.comment_url && (
                <Link to={finding.comment_url} target="_blank" targetBlankIcon className="text-xs">
                    View comment
                </Link>
            )}
        </>
    )
}

/** The "Not posted" tab for a single-agent turn: findings it raised but dropped as repeats, on unchanged code, or over the limit. */
function DrawerNotPostedTab(): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewDetail) {
        return <DrawerFindingsSkeleton />
    }
    if (!reviewDetail.dropped_findings.length) {
        return (
            <div className="text-sm text-secondary">
                {singleAgentCounts(reviewDetail).raised !== null
                    ? "This review didn't record the issues it left out."
                    : 'This review posted every issue it raised.'}
            </div>
        )
    }
    const dropped = [...reviewDetail.dropped_findings].sort(
        (a, b) =>
            DROP_REASON_ORDER.indexOf(a.disposition) - DROP_REASON_ORDER.indexOf(b.disposition) ||
            (a.rank ?? 0) - (b.rank ?? 0)
    )
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                Raised during this review but not posted to the pull request, each with the reason.
            </p>
            <div className="flex flex-col divide-y divide-primary">
                {dropped.map((finding, i) => (
                    <FindingCard key={i} finding={finding} reason={<DropReason finding={finding} />} />
                ))}
            </div>
        </div>
    )
}

/** The "Below threshold" tab: findings the validator kept, but the user's urgency bar held back. */
function DrawerBelowThresholdTab(): JSX.Element {
    const { reviewFindingsSplit } = useValues(reviewHogSettingsLogic)

    if (!reviewFindingsSplit) {
        return <DrawerFindingsSkeleton />
    }
    if (!reviewFindingsSplit.belowThreshold.length) {
        return (
            <div className="text-sm text-secondary">
                Nothing was held back — every validated finding crossed the review's urgency threshold.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                Validated as real, but under the urgency bar this review ran with — kept here instead of the pull
                request.
            </p>
            <div className="flex flex-col divide-y divide-primary">
                {reviewFindingsSplit.belowThreshold.map((finding, i) => (
                    <FindingCard key={i} finding={finding} />
                ))}
            </div>
        </div>
    )
}

/** The "Dismissed" tab: findings that failed validation, each with the validator's reasoning. */
function DrawerDismissedTab(): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewDetail) {
        return <DrawerFindingsSkeleton />
    }
    if (!reviewDetail.dismissed_findings.length) {
        return <div className="text-sm text-secondary">The validator dismissed nothing on this review.</div>
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                Raised during review, judged not worth your time — each with the validator's reasoning.
            </p>
            <div className="flex flex-col divide-y divide-primary">
                {reviewDetail.dismissed_findings.map((finding, i) => (
                    <FindingCard key={i} finding={finding} dismissed />
                ))}
            </div>
        </div>
    )
}

/** The "Chunks" tab: how the PR was split, each chunk's files (expandable), and its perspective picks. */
function DrawerChunksTab(): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewDetail) {
        return <DrawerFindingsSkeleton />
    }
    const selection = reviewDetail.perspective_selection
    if (!selection) {
        return (
            <div className="text-sm text-secondary">
                No chunk plan was recorded for this review — it ran before per-chunk planning existed, or the planner
                fell back to running every perspective on every chunk.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                How the pull request was split for review, and which perspectives each chunk actually needed — every
                skipped lens saves a full review session.
            </p>
            <div className="flex flex-col divide-y divide-primary">
                {selection.chunks.map((chunk) => (
                    <div key={chunk.chunk_id} className="flex flex-col gap-1.5 py-3">
                        <div className="flex items-baseline gap-2">
                            <span className="text-sm font-semibold">Chunk {chunk.chunk_id}</span>
                            {chunk.chunk_type && (
                                <LemonTag type="muted" size="small">
                                    {prettifyCategory(chunk.chunk_type)}
                                </LemonTag>
                            )}
                        </div>
                        {chunk.files.length > 0 && (
                            <LemonCollapse
                                embedded
                                size="xsmall"
                                panels={[
                                    {
                                        key: 'files',
                                        header: (
                                            <span className="flex min-w-0 items-baseline gap-2 text-xs">
                                                <span className="shrink-0">
                                                    {chunk.files.length} file{chunk.files.length === 1 ? '' : 's'}
                                                </span>
                                                <span className="truncate font-mono font-normal text-tertiary">
                                                    {chunk.files.join(' · ')}
                                                </span>
                                            </span>
                                        ),
                                        content: (
                                            <ul className="m-0 flex list-none flex-col gap-0.5 p-0 font-mono text-xs text-secondary">
                                                {chunk.files.map((file) => (
                                                    <li key={file}>{file}</li>
                                                ))}
                                            </ul>
                                        ),
                                    },
                                ]}
                            />
                        )}
                        <div className="flex flex-wrap items-center gap-1.5">
                            {chunk.perspectives.map((name) => (
                                <LemonTag key={name} type="muted" size="small">
                                    {perspectiveLabel(name)}
                                </LemonTag>
                            ))}
                            {chunk.skipped.map((name) => (
                                <LemonTag key={name} type="muted" size="small" className="line-through opacity-60">
                                    {perspectiveLabel(name)}
                                </LemonTag>
                            ))}
                        </div>
                        {chunk.reason && <div className="text-xs text-secondary">{chunk.reason}</div>}
                    </div>
                ))}
            </div>
        </div>
    )
}

/** The "How it ran" tab for a single-agent turn, which has no chunk plan to show. */
function DrawerHowItRanTab(): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewDetail) {
        return <DrawerFindingsSkeleton />
    }
    const lenses = singleAgentLensCount(reviewDetail)
    const { posted, raised } = singleAgentCounts(reviewDetail)
    const issuesRaised = reviewDetail.perspective_issue_count
    return (
        <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm text-secondary">
            {lenses !== null && (
                <li>
                    Ran the main review and {lenses} lens{lenses === 1 ? '' : 'es'}
                </li>
            )}
            {reviewDetail.files_reviewed !== null && <li>Read {reviewDetail.files_reviewed} files</li>}
            {issuesRaised !== null && (
                <li>
                    Raised {issuesRaised} issues
                    {raised !== null
                        ? `; ${raised - posted} not posted (repeats, unchanged code, or over the limit)`
                        : ''}
                </li>
            )}
        </ul>
    )
}

function ReviewDetailDrawer(): JSX.Element {
    const {
        reviewDrawerOpen,
        openedReview,
        reviewDetail,
        reviewDrawerTab,
        reviewFindingsSplit,
        perspectiveScoreboard,
    } = useValues(reviewHogSettingsLogic)
    const { closeReviewDrawer, setReviewDrawerTab } = useActions(reviewHogSettingsLogic)

    // The list row carries the header facts, so the drawer opens instantly while findings load.
    const review = reviewDetail ?? openedReview
    const singleAgent = isSingleAgentReview(review)

    const tabs: (LemonTab<ReviewDrawerTab> | false)[] = [
        {
            key: 'published',
            // "Published" is a claim about the PR — only make it when the review
            // actually posted; findings a store-only run kept above the bar read
            // "Kept". `review` falls back to the list row, so a published review
            // doesn't flash "Kept" while its detail loads.
            label: `${review?.published ? (singleAgent ? 'Posted' : 'Published') : 'Kept'}${
                reviewFindingsSplit ? ` (${reviewFindingsSplit.published.length})` : ''
            }`,
            content: <DrawerPublishedTab />,
        },
        singleAgent && {
            key: 'not_posted',
            label: `Not posted${reviewDetail ? ` (${reviewDetail.dropped_findings.length})` : ''}`,
            content: <DrawerNotPostedTab />,
        },
        // A single-agent turn publishes at every urgency, so nothing sits below a threshold.
        !singleAgent && {
            key: 'below_threshold',
            label: `Below threshold${reviewFindingsSplit ? ` (${reviewFindingsSplit.belowThreshold.length})` : ''}`,
            content: <DrawerBelowThresholdTab />,
        },
        // A single-agent turn has no validator, so there are no dismissals to show.
        !singleAgent && {
            key: 'dismissed',
            label: `Dismissed${reviewDetail ? ` (${reviewDetail.dismissed_findings.length})` : ''}`,
            content: <DrawerDismissedTab />,
        },
        singleAgent
            ? { key: 'how_it_ran', label: 'How it ran', content: <DrawerHowItRanTab /> }
            : { key: 'chunks', label: 'Chunks', content: <DrawerChunksTab /> },
        {
            key: 'review',
            label: 'Review body',
            content: reviewDetail ? (
                reviewDetail.report_markdown ? (
                    <LemonMarkdown className="text-sm" disableImages>
                        {reviewDetail.report_markdown}
                    </LemonMarkdown>
                ) : (
                    <div className="text-sm text-secondary">No review body was rendered for this pull request.</div>
                )
            ) : (
                <LemonSkeleton className="h-40 w-full" />
            ),
        },
    ]

    return (
        <LemonDrawer
            isOpen={reviewDrawerOpen}
            onClose={closeReviewDrawer}
            title={review ? reviewTitle(review) : ''}
            description={
                review ? (
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span>
                            {review.repository}#{review.pr_number ?? review.head_branch}
                            {review.pr_author ? ` · by ${review.pr_author}` : ''}
                        </span>
                        <ReviewModeTag mode={review.review_mode} />
                        {review.status_comment_url && (
                            <Link to={review.status_comment_url} target="_blank" targetBlankIcon>
                                Status comment
                            </Link>
                        )}
                    </span>
                ) : undefined
            }
            width={640}
            footer={
                review ? (
                    <LemonButton type="secondary" to={review.github_url} targetBlank icon={<IconExternal />}>
                        {review.github_url.includes('/pull/') ? 'View PR on GitHub' : 'View branch on GitHub'}
                    </LemonButton>
                ) : undefined
            }
        >
            <div className="flex flex-col gap-2">
                {reviewDetail && singleAgent ? (
                    <SingleAgentDrawerSummary review={reviewDetail} />
                ) : reviewDetail ? (
                    <div className="text-sm text-secondary">
                        <span className="font-semibold text-default">{reviewDetail.candidate_count}</span> findings
                        raised · <span className="font-semibold text-default">{reviewDetail.findings.length}</span> kept
                        after validation ·{' '}
                        <span className="font-semibold text-default">{reviewDetail.dismissed_count}</span> dismissed by
                        your quality bar
                    </div>
                ) : (
                    <LemonSkeleton className="h-5 w-80" />
                )}
                {perspectiveScoreboard && (
                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                        <span>Found by:</span>
                        {perspectiveScoreboard.map(({ skillName, count }) => (
                            <LemonTag key={skillName} type="muted" size="small">
                                {perspectiveLabel(skillName)} {count}
                            </LemonTag>
                        ))}
                    </div>
                )}
                <LemonTabs<ReviewDrawerTab>
                    // Standard and Deep show different tabs, and a deep link can pick a tab before the
                    // detail says which design ran, so a selection the design lacks falls back to the posted tab.
                    activeKey={tabs.some((tab) => tab && tab.key === reviewDrawerTab) ? reviewDrawerTab : 'published'}
                    onChange={setReviewDrawerTab}
                    tabs={tabs}
                />
            </div>
        </LemonDrawer>
    )
}

export const scene: SceneExport = {
    component: CodeReviewScene,
    logic: reviewHogSettingsLogic,
}

function ActivityTab(): JSX.Element {
    return (
        <>
            <TriggerReviewSection />
            <ReviewsSection />
            <PipelineSection />
        </>
    )
}

function SettingsTab(): JSX.Element {
    return (
        <>
            <StandardArea />
            <DeepArea />
            <InboxSection />
        </>
    )
}

/**
 * The "Code review" scene: ReviewHog's activity and settings page, split into an Activity tab
 * (trigger a review, recent reviews, the pipeline) and a Settings tab (the Standard area with who gets
 * automatic reviews, the Deep area with its settings and review skills, then Inbox).
 * Every control is live from load, no save step. See `reviewHogSettingsLogic` for the data flow.
 * Access is gated on FEATURE_FLAGS.REVIEW_HOG, the same flag that shows the menu entry, so whoever
 * discovers the entry can open the page.
 */
export function CodeReviewScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab, initialLoadFailed } = useValues(reviewHogSettingsLogic)
    const { setActiveTab, loadAll } = useActions(reviewHogSettingsLogic)

    if (!featureFlags[FEATURE_FLAGS.REVIEW_HOG]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Code review"
                description="PostHog Review reads your pull requests and posts the findings worth fixing. Start a review, see recent ones, and choose what gets reviewed."
                resourceType={{ type: 'code_review' }}
            />
            <LemonTabs<CodeReviewTab>
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    { key: 'activity', label: 'Activity', 'data-attr': 'code-review-tab-activity' },
                    { key: 'settings', label: 'Settings', 'data-attr': 'code-review-tab-settings' },
                ]}
                sceneInset
            />
            <div className="flex flex-col gap-8 pb-8">
                {initialLoadFailed && (
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadAll() }}>
                        Some PostHog Review settings failed to load.
                    </LemonBanner>
                )}

                {activeTab === 'activity' ? <ActivityTab /> : <SettingsTab />}

                {/* Overlays stay mounted on both tabs, so a `?review=` deep link opens on either. */}
                <AdoptSkillModal />
                <PipelineDetailModal />
                <ReviewDetailDrawer />
            </div>
        </SceneContent>
    )
}

export default CodeReviewScene
