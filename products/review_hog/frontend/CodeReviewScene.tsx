import { useActions, useValues } from 'kea'

import { IconChevronDown, IconExternal } from '@posthog/icons'
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
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
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
 * Scope of the reviews table. It also scopes the proof card. Skill toggles stay per-user
 * regardless of scope.
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
    const owner = reviewsScope === ReviewHogReviewsListScope.Everyone ? "The project's" : 'Your'
    return (
        <Tooltip title={scopeOption?.tooltip}>
            <span className="text-xxs text-tertiary">
                <span translate="no">{`${owner} last ${reportCount} completed review${reportCount === 1 ? '' : 's'}`}</span>
            </span>
        </Tooltip>
    )
}

/**
 * Proof block: the validation funnel across the in-scope recent reviews. Hidden while there are
 * no reviewed findings in scope yet.
 */
function ProofCard(): JSX.Element | null {
    const { perspectiveStats } = useValues(reviewHogSettingsLogic)

    if (perspectiveStats === null) {
        return <LemonSkeleton className="h-16 w-full" />
    }
    const raised = perspectiveStats.perspectives.reduce((sum, p) => sum + p.raised, 0)
    const kept = perspectiveStats.perspectives.reduce((sum, p) => sum + p.kept, 0)
    const dismissed = perspectiveStats.perspectives.reduce((sum, p) => sum + p.dismissed, 0)
    if (raised === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 px-4 py-3">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-xl font-bold tabular-nums">{kept}</span>
                <span className="text-sm">
                    of <span className="font-semibold">{raised}</span> findings kept
                </span>
                <span className="text-xs text-secondary">
                    <span className="font-semibold text-default">{dismissed}</span> dismissed
                </span>
                <span className="ml-auto">
                    <StatsWindowLabel reportCount={perspectiveStats.report_count} />
                </span>
            </div>
            <LemonProgress
                percent={(kept / raised) * 100}
                strokeColor="var(--success)"
                bgColor="var(--color-bg-fill-highlight-100)"
            />
        </LemonCard>
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

/** Scoreboard label for a finding's source skill. Blind-spot skills all read as one sweep. */
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

/** The drawer header for a single-agent turn: how it ran, how many issues it posted, and how many it raised but left out. */
function SingleAgentDrawerSummary({ review }: { review: ReviewDetailApi }): JSX.Element {
    const { setReviewDrawerTab } = useActions(reviewHogSettingsLogic)
    const { posted, raised } = singleAgentCounts(review)
    const lenses = singleAgentLensCount(review)
    const lensText = lenses
        ? ` plus ${lenses} ${lenses === 1 ? 'lens that focuses' : 'lenses that each focus'} on one area`
        : ''
    const notPostedLabel = `${raised !== null ? raised - posted : 0} not posted`
    return (
        <div className="flex flex-col gap-1 text-sm text-secondary">
            <div>{`Standard review: one main pass over the whole pull request${lensText}. No separate validation step.`}</div>
            <div>
                {/* A turn whose GitHub publish failed kept its findings without posting them. */}
                <span>{review.turn_published ? 'Posted' : 'Kept'}</span>{' '}
                <span className="font-semibold text-default">{posted}</span>
                {raised !== null ? (
                    <>
                        {' '}
                        of <span className="font-semibold text-default">{raised}</span> issues raised,{' '}
                        {/* Turns that predate the dropped-finding record have nothing to switch to. */}
                        {review.dropped_findings.length ? (
                            <Link onClick={() => setReviewDrawerTab('not_posted')}>{notPostedLabel}</Link>
                        ) : (
                            <span>{notPostedLabel}</span>
                        )}
                    </>
                ) : (
                    ` issue${posted === 1 ? '' : 's'}`
                )}
            </div>
        </div>
    )
}

function ReviewsSection(): JSX.Element {
    return (
        <SceneSection title="Reviews" actions={<ReviewsScopeFilter />}>
            <ProofCard />
            <ReviewsFilters />
            <ReviewsTable />
        </SceneSection>
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
    const { setTriggerPrUrl, submitTriggerReview, openPipelineDetail } = useActions(reviewHogSettingsLogic)

    const noUrlReason = !triggerPrUrl.trim() ? 'Paste a pull request URL first' : undefined
    // Mirrors the server-side busy-guard for PRs visible in the list; pasted URLs outside it still
    // get the same refusal from the trigger endpoint.
    const resolvingReason = triggerUrlResolving ? 'Still resolving comments from the last review' : undefined
    const inFlightReason = triggeringReview ? 'A run is already starting…' : undefined
    const flashAfterFullReason = triggerUrlHasFullReview
        ? 'This pull request already has a Deep review. Standard does not run after one.'
        : undefined
    return (
        <SceneSection
            className="max-w-200"
            title="Review a pull request"
            description="PostHog Review runs a Deep review and posts it to the pull request."
            actions={
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => openPipelineDetail()}
                    data-attr="review-pipeline-detailed-view"
                >
                    How we review your PRs
                </LemonButton>
            }
        >
            <form
                className="flex flex-wrap items-center gap-2"
                onSubmit={(e) => {
                    e.preventDefault()
                    submitTriggerReview()
                }}
            >
                <LemonInput
                    className="min-w-80 flex-1"
                    placeholder="https://github.com/PostHog/posthog.com/pull/1234"
                    aria-label="Pull request URL"
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
                                        tooltip="This review does not touch the comment threads, whatever your Resolve setting is."
                                    >
                                        Review without resolving comments
                                    </LemonButton>
                                    <LemonButton
                                        fullWidth
                                        onClick={() =>
                                            submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.ResolveOnly)
                                        }
                                        tooltip="This skips the review and replies to or fixes the unresolved comment threads."
                                    >
                                        Only resolve existing comments
                                    </LemonButton>
                                    <LemonButton
                                        fullWidth
                                        onClick={() => submitTriggerReview(ReviewTriggerRequestRunModeEnumApi.Flash)}
                                        tooltip="A Standard review costs less. It does not resolve comments or use your review skills."
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
        </SceneSection>
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
        ? `${finding.file}:${finding.lines.map((r) => (r.end && r.end !== r.start ? `${r.start}-${r.end}` : `${r.start}`)).join(', ')}`
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
            {/* Collapsed by default, like the published PR comment, so the title and location stay scannable. */}
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
                                  header: dismissed ? 'Why it was dismissed' : 'Why it was kept',
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

/** The first drawer tab, "Posted" or "Kept": the findings that crossed the urgency threshold, caveated while unpublished. */
function DrawerPublishedTab(): JSX.Element {
    const { reviewFindingsSplit, reviewDetail } = useValues(reviewHogSettingsLogic)

    if (!reviewFindingsSplit) {
        return <DrawerFindingsSkeleton />
    }
    const isPublished = reviewDetail?.published ?? false
    if (!reviewFindingsSplit.published.length && isSingleAgentReview(reviewDetail)) {
        return <div className="text-sm text-secondary">This review found nothing to post.</div>
    }
    if (!reviewFindingsSplit.published.length) {
        return (
            <div className="text-sm text-secondary">
                {isPublished
                    ? 'No findings met the threshold, so the review posted nothing.'
                    : 'No findings met the threshold, and the review is not posted.'}
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            {!isPublished && (
                <p className="m-0 text-xs text-secondary">This review is not posted to the pull request yet.</p>
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
    budget: 'Over the pull request limit',
}

// Display order of the reasons: the label map's key order.
const DROP_REASON_ORDER = Object.keys(DROP_REASON_LABEL) as ReviewDropDispositionEnumApi[]

function DropReason({ finding }: { finding: ReviewDroppedFindingApi }): JSX.Element {
    const label = DROP_REASON_LABEL[finding.disposition]
    return (
        <>
            <LemonTag type="muted" size="small">
                {(finding.disposition === 'cap' || finding.disposition === 'budget') && finding.rank
                    ? `${label} (#${finding.rank})`
                    : label}
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
        <div className="flex flex-col divide-y divide-primary">
            {dropped.map((finding, i) => (
                <FindingCard key={i} finding={finding} reason={<DropReason finding={finding} />} />
            ))}
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
        return <div className="text-sm text-secondary">No findings below the threshold.</div>
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                The review kept these findings but did not post them, because they are below its threshold.
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
        return <div className="text-sm text-secondary">No dismissed findings.</div>
    }
    return (
        <div className="flex flex-col divide-y divide-primary">
            {reviewDetail.dismissed_findings.map((finding, i) => (
                <FindingCard key={i} finding={finding} dismissed />
            ))}
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
        return <div className="text-sm text-secondary">No chunk plan was recorded for this review.</div>
    }
    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-xs text-secondary">
                Each chunk lists the perspectives it ran. Skipped perspectives are struck through.
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
            // "Posted" is a claim about the PR, so only make it when the review
            // actually posted; findings a store-only run kept above the bar read
            // "Kept". `review` falls back to the list row, so a published review
            // doesn't flash "Kept" while its detail loads.
            label: `${review?.published ? 'Posted' : 'Kept'}${
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
                    <div className="text-sm text-secondary">No review body for this pull request.</div>
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
                            {review.pr_author ? ` by ${review.pr_author}` : ''}
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
                        raised, <span className="font-semibold text-default">{reviewDetail.findings.length}</span> kept
                        after validation,{' '}
                        <span className="font-semibold text-default">{reviewDetail.dismissed_count}</span> dismissed
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
        </>
    )
}

/**
 * The "Code review" scene: ReviewHog's activity and settings page, split into an Activity tab
 * (trigger a review, recent reviews), a My preferences tab (the viewer's own choices), and a
 * Project settings tab (the rules and defaults that project admins set for everyone).
 * Every control is live from load, no save step. See `reviewHogSettingsLogic` for the data flow.
 * Access is gated on FEATURE_FLAGS.REVIEW_HOG, the same flag that shows the menu entry, so whoever
 * discovers the entry can open the page.
 */
export function CodeReviewScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab, initialLoadFailed, featureFlagGated } = useValues(reviewHogSettingsLogic)
    const { setActiveTab, loadAll } = useActions(reviewHogSettingsLogic)

    if (!featureFlags[FEATURE_FLAGS.REVIEW_HOG]) {
        return <NotFound object="page" />
    }

    const titleSection = (
        <SceneTitleSection
            name="Code review"
            description="Automated code reviews of your pull requests."
            resourceType={{ type: 'code_review' }}
        />
    )

    // The browser flag shows the page, but the server flag gate refuses its API.
    if (featureFlagGated) {
        return (
            <SceneContent>
                {titleSection}
                <LemonBanner type="info" data-attr="code-review-feature-flag-gated">
                    PostHog Review is not available for this project yet. If you just turned on the feature preview,
                    refresh the page in a moment. Otherwise, ask an admin of your PostHog instance to turn it on.
                </LemonBanner>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            {titleSection}
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

                {activeTab === 'activity' ? (
                    <ActivityTab />
                ) : (
                    <>
                        <StandardArea />
                        <DeepArea />
                        <InboxSection />
                    </>
                )}

                {/* Overlays stay mounted on every tab, so a `?review=` deep link opens on any of them. */}
                <AdoptSkillModal />
                <PipelineDetailModal />
                <ReviewDetailDrawer />
            </div>
        </SceneContent>
    )
}

export default CodeReviewScene
