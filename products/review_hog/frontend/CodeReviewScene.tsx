import { useActions, useValues } from 'kea'

import { IconChevronDown, IconDirectedGraph, IconExternal, IconGithub, IconPullRequest } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonTabs,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
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
    ReviewFindingApi,
    ReviewIssuePriorityEnumApi,
    ReviewPerspectiveStatItemApi,
    ReviewRecentReviewApi,
    ReviewResolutionStatusApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import {
    ReviewHogReviewsListScope,
    ReviewTriggerRequestRunModeEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { AdoptSkillModal } from './AdoptSkillModal'
import { PipelineDetailModal } from './PipelineDetailModal'
import { InstallationClaims } from './repositories/InstallationClaims'
import { RepositoriesPanes } from './repositories/RepositoriesPanes'
import { CodeReviewTab, REVIEWS_PAGE_SIZE, ReviewDrawerTab, reviewHogSettingsLogic } from './reviewHogSettingsLogic'
import { SectionHeader } from './SectionHeader'
import { FullReviewSettingsSection } from './settings/FullReviewSettingsSection'
import { InboxSection } from './settings/InboxSection'
import { ReviewSkillsPanel } from './settings/ReviewSkillsPanel'
import { prettifySkillName } from './skillNames'

// Step numbering and names match the detailed-view modal (PipelineDetailModal) — keep them in sync.
const PIPELINE_PHASES: { name: string; hint: string; steps: { number: string; title: string; caption: string }[] }[] = [
    {
        name: 'Prepare',
        hint: 'get the diff ready to read',
        steps: [
            {
                number: '01',
                title: 'Meaningful diff',
                caption: "we fetch the PR's diff; generated files, lock files, and snapshots are skipped",
            },
            {
                number: '02',
                title: 'Split into chunks',
                caption: 'larger PRs are split into logically reviewable chunks',
            },
        ],
    },
    {
        name: 'Review',
        hint: 'pick the lenses, read in parallel',
        steps: [
            {
                number: '03',
                title: 'Pick perspectives',
                caption: 'each chunk gets only the perspectives it actually needs',
            },
            { number: '04', title: 'Perspectives', caption: 'specialist reviewers read each chunk in parallel' },
            { number: '05', title: 'Blind spots', caption: 'one more sweep for what every perspective missed' },
        ],
    },
    {
        name: 'Refine & publish',
        hint: 'clean up and ship the review',
        steps: [
            { number: '06', title: 'Dedupe', caption: 'overlapping findings are merged' },
            { number: '07', title: 'Validate', caption: 'each finding is checked against your quality bar' },
            { number: '08', title: 'Publish', caption: 'a cleaned-up review lands on the pull request' },
        ],
    },
    {
        name: 'Resolve',
        hint: 'settle the review comments',
        steps: [
            {
                number: '09',
                title: 'Triage threads',
                caption: 'every unresolved comment thread is judged against your resolution criteria',
            },
            {
                number: '10',
                title: 'Fix & reply',
                caption: 'worth-and-safe asks land on the branch, and every thread gets a reply',
            },
        ],
    },
]

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
 * Filter on the recent-reviews list. It also scopes the proof card and the effectiveness cards on
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
        <Tooltip title={`${scopeOption?.tooltip}. Set by the Mine / Everyone filter on recent reviews.`}>
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
            <div className="flex flex-wrap items-stretch gap-2.5">
                {PIPELINE_PHASES.map((phase, i) => (
                    <div key={phase.name} className="flex min-w-52 flex-1 items-center gap-2.5">
                        {i > 0 && <span className="shrink-0 text-lg text-tertiary">→</span>}
                        <LemonCard hoverEffect={false} className="flex h-full flex-1 flex-col gap-3 p-4">
                            <div className="flex flex-col">
                                <span className="text-sm font-semibold">{phase.name}</span>
                                <span className="text-xs text-tertiary">{phase.hint}</span>
                            </div>
                            <div className="flex flex-col gap-2.5">
                                {phase.steps.map((step) => (
                                    <div key={step.number} className="flex items-baseline gap-2">
                                        <span className="font-mono text-xxs text-warning">{step.number}</span>
                                        <div className="flex flex-col">
                                            <span className="text-xs font-semibold">{step.title}</span>
                                            <span className="text-xxs text-tertiary">{step.caption}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </LemonCard>
                    </div>
                ))}
            </div>
            <PipelineDetailModal />
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

/** Scoreboard label for a finding's source skill — blind-spot skills all read as one sweep. */
function perspectiveLabel(skillName: string): string {
    if (skillName.startsWith('review-hog-blind-spots-')) {
        return 'Blind spots'
    }
    if (skillName === 'unknown') {
        return 'Unknown'
    }
    return prettifySkillName(skillName)
}

const COUNT_CHIPS: {
    key: 'must_fix_count' | 'should_fix_count' | 'consider_count'
    label: string
    dot: string
    text: string
}[] = [
    { key: 'must_fix_count', label: 'must fix', dot: 'bg-danger', text: 'text-danger' },
    { key: 'should_fix_count', label: 'should fix', dot: 'bg-warning', text: 'text-warning' },
    { key: 'consider_count', label: 'consider', dot: 'bg-border-bold', text: 'text-secondary' },
]

function FindingCounts({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const total = review.must_fix_count + review.should_fix_count + review.consider_count
    if (total === 0) {
        return <span>No findings</span>
    }
    return (
        <span className="flex items-center gap-2.5">
            {COUNT_CHIPS.filter((chip) => review[chip.key] > 0).map((chip) => (
                <span key={chip.key} className="flex items-center gap-1 whitespace-nowrap">
                    <span className={`size-1.5 rounded-full ${chip.dot}`} />
                    <span className={`font-semibold tabular-nums ${chip.text}`}>{review[chip.key]}</span>
                    <span>{chip.label}</span>
                </span>
            ))}
        </span>
    )
}

/** Leading status dot: red when the review found a blocker, gold for other findings, green for a clean pass. */
function ReviewStatusDot({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const total = review.must_fix_count + review.should_fix_count + review.consider_count
    const color = review.must_fix_count > 0 ? 'bg-danger' : total > 0 ? 'bg-warning' : 'bg-success'
    return (
        <span className="flex w-6 shrink-0 justify-center">
            <span className={`size-2 rounded-full ${color}`} />
        </span>
    )
}

function reviewTitle(review: ReviewRecentReviewApi): string {
    return review.pr_title ?? `${review.repository}#${review.pr_number ?? review.head_branch}`
}

function progressLabel(review: ReviewRecentReviewApi): string {
    if (!review.progress) {
        return 'Review in progress'
    }
    // Steps match the pipeline as users think of it: chunking → pick perspectives → review →
    // dedupe → validation → finalize. Fetching folds into step 1.
    const { review_stage, done, total } = review.progress
    const percent = done !== null && total !== null && total > 0 ? ` · ${Math.round((done / total) * 100)}%` : ''
    switch (review_stage) {
        case 'fetching':
            return 'Step 1/6 · Preparing the diff'
        case 'chunking':
            return 'Step 1/6 · Splitting into chunks'
        case 'selecting':
            return 'Step 2/6 · Picking perspectives'
        case 'reviewing':
            return `Step 3/6 · Running review passes${percent}`
        case 'deduplicating':
            return 'Step 4/6 · Merging overlapping findings'
        case 'validating':
            return `Step 5/6 · Validating findings${percent}`
        case 'finalizing':
            return 'Step 6/6 · Finalizing the review'
        case 'single_agent_preparing':
            return 'Step 1/3 · Preparing the diff'
        case 'single_agent_reviewing':
            return 'Step 2/3 · Reviewing the pull request'
        case 'single_agent_finalizing':
            return 'Step 3/3 · Finalizing the review'
    }
}

/** The live resolution run's row label, e.g. "Resolving comments · 6/10 · 5 fixed, 1 needs you". */
function resolutionLabel(resolution: ReviewResolutionStatusApi): string {
    const outcomes = [
        resolution.fixed > 0 ? `${resolution.fixed} fixed` : null,
        resolution.needs_attention > 0
            ? `${resolution.needs_attention} need${resolution.needs_attention === 1 ? 's' : ''} you`
            : null,
    ].filter(Boolean)
    return `Resolving comments · ${resolution.done}/${resolution.total}${outcomes.length ? ` · ${outcomes.join(', ')}` : ''}`
}

/** A first review still running: no findings to expand into yet, just the live stage. */
function RunningReviewRow({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const { showReviewAuthor } = useValues(reviewHogSettingsLogic)
    const showAuthor = showReviewAuthor(review)
    return (
        <div className="flex items-center gap-3 px-4 py-3">
            <span className="flex w-6 shrink-0 justify-center">
                <Spinner className="text-lg" />
            </span>
            <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{reviewTitle(review)}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-secondary">
                    <span className="whitespace-nowrap font-mono text-tertiary">
                        {review.repository}#{review.pr_number ?? review.head_branch}
                    </span>
                    {showAuthor && (
                        <>
                            <span className="text-tertiary">·</span>
                            <span className="whitespace-nowrap">by {review.pr_author}</span>
                        </>
                    )}
                    <span className="text-tertiary">·</span>
                    <span className="whitespace-nowrap font-medium text-warning">
                        {review.resolution?.resolution_status === 'resolving'
                            ? resolutionLabel(review.resolution)
                            : progressLabel(review)}
                    </span>
                </div>
            </div>
            <LemonButton size="small" type="secondary" to={review.github_url} targetBlank sideIcon={<IconExternal />}>
                {review.github_url.includes('/pull/') ? 'View PR' : 'View branch'}
            </LemonButton>
        </div>
    )
}

/** One expandable review row: essentials collapsed; PR facts + funnel + findings entry when open. */
function RecentReviewRow({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const { expandedReviewIds, showReviewAuthor } = useValues(reviewHogSettingsLogic)
    const { toggleReviewRowExpanded, openReviewDetail } = useActions(reviewHogSettingsLogic)
    const expanded = expandedReviewIds.includes(review.id)
    const validated = review.must_fix_count + review.should_fix_count + review.consider_count
    const showAuthor = showReviewAuthor(review)

    // A first review has no completed turn to expand into — it renders as a live progress row.
    if (review.in_progress && review.run_count === 0) {
        return <RunningReviewRow review={review} />
    }

    return (
        <div className="flex flex-col">
            <div
                role="button"
                tabIndex={0}
                aria-expanded={expanded}
                onClick={() => toggleReviewRowExpanded(review.id)}
                onKeyDown={(e) => e.key === 'Enter' && toggleReviewRowExpanded(review.id)}
                className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-fill-highlight-50"
            >
                <ReviewStatusDot review={review} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold">{reviewTitle(review)}</span>
                        {review.resolution?.resolution_status === 'resolving' ? (
                            <LemonTag type="warning" size="small" className="inline-flex items-center gap-1">
                                <Spinner className="text-xs" /> {resolutionLabel(review.resolution)}
                            </LemonTag>
                        ) : review.in_progress ? (
                            <LemonTag type="warning" size="small" className="inline-flex items-center gap-1">
                                <Spinner className="text-xs" /> Re-reviewing · {progressLabel(review)}
                            </LemonTag>
                        ) : review.resolution?.resolution_status === 'stopped' ? (
                            <LemonTag type="muted" size="small">
                                Resolution didn't finish · stopped at {review.resolution.done}/{review.resolution.total}
                            </LemonTag>
                        ) : null}
                        {!review.published && (
                            <LemonTag type="muted" size="small">
                                Not published
                            </LemonTag>
                        )}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-secondary">
                        <span className="whitespace-nowrap font-mono text-tertiary">
                            {review.repository}#{review.pr_number ?? review.head_branch}
                        </span>
                        {showAuthor && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">by {review.pr_author}</span>
                            </>
                        )}
                        <span className="text-tertiary">·</span>
                        <FindingCounts review={review} />
                        {review.last_run_at && (
                            <>
                                <span className="text-tertiary">·</span>
                                <TZLabel time={review.last_run_at} />
                            </>
                        )}
                    </div>
                </div>
                {/* stopPropagation so the buttons don't also toggle the row */}
                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <LemonButton
                        size="small"
                        type="secondary"
                        to={review.github_url}
                        targetBlank
                        sideIcon={<IconExternal />}
                    >
                        {review.github_url.includes('/pull/') ? 'View PR' : 'View branch'}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        aria-label={expanded ? 'Hide review details' : 'Show review details'}
                        icon={<IconChevronDown className={expanded ? 'rotate-180' : ''} />}
                        onClick={() => toggleReviewRowExpanded(review.id)}
                    />
                </div>
            </div>
            {expanded && (
                <div className="flex flex-col gap-2 border-t border-primary bg-fill-highlight-50 py-3 pl-13 pr-4">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-secondary">
                        {review.pr_author && <span className="whitespace-nowrap">by {review.pr_author}</span>}
                        {review.additions !== null && review.deletions !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap font-mono">
                                    <span className="text-success">+{review.additions}</span>{' '}
                                    <span className="text-danger">−{review.deletions}</span>
                                </span>
                            </>
                        )}
                        {review.changed_files !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">{review.changed_files} files changed</span>
                            </>
                        )}
                        {review.files_reviewed !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">{review.files_reviewed} reviewed</span>
                            </>
                        )}
                        {review.chunk_count !== null && (
                            <>
                                <span className="text-tertiary">·</span>
                                <span className="whitespace-nowrap">
                                    {review.chunk_count} chunk{review.chunk_count === 1 ? '' : 's'}
                                </span>
                            </>
                        )}
                        <span className="text-tertiary">·</span>
                        <span className="whitespace-nowrap">
                            {review.run_count} review turn{review.run_count === 1 ? '' : 's'}
                        </span>
                    </div>
                    <div className="text-xs text-secondary">
                        <span className="font-semibold text-default">{review.candidate_count}</span> findings raised →{' '}
                        <span className="font-semibold text-default">{validated}</span> kept after validation →{' '}
                        <span className="font-semibold text-default">{review.dismissed_count}</span> dismissed
                    </div>
                    <div>
                        <LemonButton size="small" type="secondary" onClick={() => openReviewDetail(review)}>
                            View findings
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

/** Proof card and review list with their scope filter, hidden entirely until the project has reviews. */
function RecentReviewsSection(): JSX.Element | null {
    const {
        recentReviews,
        recentReviewsPageLoading,
        moreReviewsAvailable,
        reviewsExpanding,
        reviewsScope,
        hasUserChosenReviewsScope,
    } = useValues(reviewHogSettingsLogic)
    const { showMoreReviews, showFewerReviews } = useActions(reviewHogSettingsLogic)
    const everyone = reviewsScope === ReviewHogReviewsListScope.Everyone
    const loadedEmpty = recentReviews !== null && recentReviews.length === 0

    // Settled-and-empty on the Everyone scope means the project has no reviews at all — hide
    // the section entirely (an in-flight load keeps it mounted with skeletons instead of flashing
    // it away mid-switch). An empty Mine scope keeps the section, with an empty state pointing
    // at the scope filter in the section header.
    if (loadedEmpty && everyone && !recentReviewsPageLoading) {
        return null
    }
    // A stale EMPTY list must not render an empty state while a reload (scope switch, auto-default)
    // is in flight — but previous ROWS are kept during refreshes, so the in-progress poll never
    // flashes skeletons.
    const emptyAwaitingReload = loadedEmpty && (recentReviewsPageLoading || !hasUserChosenReviewsScope)

    return (
        <section className="flex flex-col gap-4">
            <SectionHeader icon={<IconPullRequest />} title="Recent reviews" action={<ReviewsScopeFilter />}>
                {everyone
                    ? 'The latest PostHog Review runs on pull requests across this project. Expand a review for its details and findings.'
                    : 'The latest PostHog Review runs on pull requests you authored, plus reviews you started. Expand a review for its details and findings.'}
            </SectionHeader>
            <ProofCard />
            <LemonCard hoverEffect={false} className="divide-y divide-primary p-0">
                {recentReviews === null || emptyAwaitingReload ? (
                    [0, 1, 2].map((i) => (
                        <div key={i} className="flex items-center gap-3 px-4 py-3">
                            <span className="flex w-6 shrink-0 justify-center">
                                <LemonSkeleton.Circle className="size-2" />
                            </span>
                            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                                <LemonSkeleton className="h-4 w-80 max-w-full" />
                                <LemonSkeleton className="h-3 w-56 max-w-full" />
                            </div>
                            <LemonSkeleton className="h-8 w-24 shrink-0" />
                        </div>
                    ))
                ) : recentReviews.length ? (
                    <>
                        {recentReviews.map((review) => (
                            <RecentReviewRow key={review.id} review={review} />
                        ))}
                        {(moreReviewsAvailable || recentReviews.length > REVIEWS_PAGE_SIZE) && (
                            <div className="flex justify-center gap-2 px-4 py-1.5">
                                {moreReviewsAvailable && (
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        onClick={showMoreReviews}
                                        loading={reviewsExpanding}
                                    >
                                        Show more
                                    </LemonButton>
                                )}
                                {recentReviews.length > REVIEWS_PAGE_SIZE && (
                                    <LemonButton size="small" type="tertiary" onClick={showFewerReviews}>
                                        Show fewer
                                    </LemonButton>
                                )}
                            </div>
                        )}
                    </>
                ) : (
                    <div className="px-4 py-6 text-center text-sm text-secondary">
                        No reviews of your pull requests or reviews you started yet. Pick "Everyone" above to see the
                        whole team's.
                    </div>
                )}
            </LemonCard>
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
                request and shows up under recent reviews. Your perspectives and other review skills apply to Deep
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

function FindingCard({ finding, dismissed }: { finding: ReviewFindingApi; dismissed?: boolean }): JSX.Element {
    const { reviewDetail } = useValues(reviewHogSettingsLogic)
    const priority = PRIORITY_TAG[finding.effective_priority]
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
                {finding.effective_priority !== finding.reviewer_priority && (
                    <LemonTag type="muted" size="small">
                        was {PRIORITY_TAG[finding.reviewer_priority].label.toLowerCase()}
                    </LemonTag>
                )}
                {finding.validator_category && (
                    <LemonTag type="muted" size="small">
                        {prettifyCategory(finding.validator_category)}
                    </LemonTag>
                )}
                {finding.source_perspective && (
                    <span className="text-xs text-tertiary">{prettifySkillName(finding.source_perspective)}</span>
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
                    {
                        key: 'suggestion',
                        header: 'Suggested fix',
                        content: (
                            <LemonMarkdown className="text-sm text-secondary" disableImages>
                                {finding.suggestion}
                            </LemonMarkdown>
                        ),
                    },
                    {
                        key: 'validator',
                        header: dismissed ? 'Why it was dismissed' : "Why we think it's a valid issue",
                        content: (
                            <LemonMarkdown className="text-sm text-secondary" disableImages>
                                {finding.validator_note}
                            </LemonMarkdown>
                        ),
                    },
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

    return (
        <LemonDrawer
            isOpen={reviewDrawerOpen}
            onClose={closeReviewDrawer}
            title={review ? reviewTitle(review) : ''}
            description={
                review
                    ? `${review.repository}#${review.pr_number ?? review.head_branch}${
                          review.pr_author ? ` · by ${review.pr_author}` : ''
                      }`
                    : undefined
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
                {reviewDetail ? (
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
                    activeKey={reviewDrawerTab}
                    onChange={setReviewDrawerTab}
                    tabs={[
                        {
                            key: 'published',
                            // "Published" is a claim about the PR — only make it when the review
                            // actually posted; findings a store-only run kept above the bar read
                            // "Kept". `review` falls back to the list row, so a published review
                            // doesn't flash "Kept" while its detail loads.
                            label: `${review?.published ? 'Published' : 'Kept'}${
                                reviewFindingsSplit ? ` (${reviewFindingsSplit.published.length})` : ''
                            }`,
                            content: <DrawerPublishedTab />,
                        },
                        {
                            key: 'below_threshold',
                            label: `Below threshold${
                                reviewFindingsSplit ? ` (${reviewFindingsSplit.belowThreshold.length})` : ''
                            }`,
                            content: <DrawerBelowThresholdTab />,
                        },
                        {
                            key: 'dismissed',
                            label: `Dismissed${reviewDetail ? ` (${reviewDetail.dismissed_findings.length})` : ''}`,
                            content: <DrawerDismissedTab />,
                        },
                        {
                            key: 'chunks',
                            label: 'Chunks',
                            content: <DrawerChunksTab />,
                        },
                        {
                            key: 'review',
                            label: 'Review body',
                            content: reviewDetail ? (
                                reviewDetail.report_markdown ? (
                                    <LemonMarkdown className="text-sm" disableImages>
                                        {reviewDetail.report_markdown}
                                    </LemonMarkdown>
                                ) : (
                                    <div className="text-sm text-secondary">
                                        No review body was rendered for this pull request.
                                    </div>
                                )
                            ) : (
                                <LemonSkeleton className="h-40 w-full" />
                            ),
                        },
                    ]}
                />
            </div>
        </LemonDrawer>
    )
}

function EffectivenessRows({
    items,
    maxRaised,
}: {
    items: ReviewPerspectiveStatItemApi[]
    maxRaised: number
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {items.map((stat) => (
                <Tooltip
                    key={stat.skill_name}
                    title={`${stat.raised} raised · ${stat.kept} kept · ${stat.dismissed} dismissed by validation`}
                >
                    <div className="flex items-center gap-3">
                        <span className="w-44 shrink-0 truncate text-xs">{prettifySkillName(stat.skill_name)}</span>
                        <div className="flex h-2 flex-1 items-center">
                            {stat.kept > 0 && (
                                <div
                                    className="h-2 rounded-sm bg-success"
                                    style={{ width: `${(stat.kept / maxRaised) * 100}%` }}
                                />
                            )}
                            {stat.dismissed > 0 && (
                                <div
                                    className="ml-0.5 h-2 rounded-sm bg-fill-highlight-100"
                                    style={{ width: `${(stat.dismissed / maxRaised) * 100}%` }}
                                />
                            )}
                        </div>
                        <span className="w-24 shrink-0 text-right text-xs tabular-nums text-secondary">
                            {stat.kept} of {stat.raised} kept
                        </span>
                    </div>
                </Tooltip>
            ))}
        </div>
    )
}

/**
 * Aggregate effectiveness across the in-scope recent reviews for one reviewer kind: per skill, a
 * bar of findings it raised split into validator-kept (green) vs dismissed (muted). Rendered once
 * for perspectives and once for blind spots, under the review skills panel; both cards share one
 * scale so bar lengths stay comparable. Hidden until there is data for the kind. On the Everyone
 * scope this can list skills beyond the user's own rows above — the stats describe the project,
 * while the toggles stay per-user.
 */
function EffectivenessCard({ kind }: { kind: 'perspectives' | 'blind_spots' }): JSX.Element | null {
    const { perspectiveStats } = useValues(reviewHogSettingsLogic)

    if (!perspectiveStats?.perspectives.length) {
        return null
    }
    const items = perspectiveStats.perspectives.filter(
        (p) => p.skill_name.startsWith('review-hog-blind-spots-') === (kind === 'blind_spots')
    )
    if (!items.length) {
        return null
    }
    const maxRaised = Math.max(...perspectiveStats.perspectives.map((p) => p.raised))
    const noun = kind === 'blind_spots' ? 'sweep' : 'perspective'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            {/* Overline header: this card is an instrument panel about the skills below, not one of
                them — it must not share the skill cards' title style. */}
            <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-xxs font-semibold uppercase tracking-wide text-tertiary">Effectiveness</span>
                    <span className="ml-auto">
                        <StatsWindowLabel reportCount={perspectiveStats.report_count} />
                    </span>
                </div>
                <p className="m-0 text-xs text-secondary">
                    Findings each {noun} raised in these reviews, and how many survived validation.
                </p>
            </div>
            <EffectivenessRows items={items} maxRaised={maxRaised} />
            <div className="flex items-center gap-4 text-xs text-tertiary">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-success" /> Kept
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-fill-highlight-100" /> Dismissed by validation
                </span>
            </div>
        </LemonCard>
    )
}

/**
 * The validator's flip side of the effectiveness cards: one bar for the whole quality bar (verdicts
 * aren't attributed to a validator skill), with dismissals as the headline — its job is filtering.
 */
function ValidatorEffectivenessCard(): JSX.Element | null {
    const { perspectiveStats, reviewsScope } = useValues(reviewHogSettingsLogic)
    const everyone = reviewsScope === ReviewHogReviewsListScope.Everyone

    if (!perspectiveStats?.perspectives.length) {
        return null
    }
    const kept = perspectiveStats.perspectives.reduce((sum, p) => sum + p.kept, 0)
    const dismissed = perspectiveStats.perspectives.reduce((sum, p) => sum + p.dismissed, 0)
    const judged = kept + dismissed
    if (judged === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-xxs font-semibold uppercase tracking-wide text-tertiary">Effectiveness</span>
                    <span className="ml-auto">
                        <StatsWindowLabel reportCount={perspectiveStats.report_count} />
                    </span>
                </div>
                <p className="m-0 text-xs text-secondary">
                    Of the <span translate="no">{judged}</span> findings reviewers raised in these reviews, this is how
                    much noise validation kept off pull requests.
                </p>
            </div>
            <Tooltip
                title={`${judged} judged · ${kept} kept · ${dismissed} dismissed by ${everyone ? 'validation' : 'your quality bar'}`}
            >
                {/* Unlike the reviewer cards, green here is the DISMISSED share — this card celebrates noise removed. */}
                <div className="flex items-center gap-3">
                    <span className="w-44 shrink-0 truncate text-xs">
                        {/* Project scope aggregates every author's active validator, not one user's bar. */}
                        {everyone ? 'Validation' : 'Your quality bar'}
                    </span>
                    <div className="flex h-2 flex-1 items-center">
                        {dismissed > 0 && (
                            <div
                                className="h-2 rounded-sm bg-success"
                                style={{ width: `${(dismissed / judged) * 100}%` }}
                            />
                        )}
                        {kept > 0 && (
                            <div
                                className="ml-0.5 h-2 rounded-sm bg-fill-highlight-100"
                                style={{ width: `${(kept / judged) * 100}%` }}
                            />
                        )}
                    </div>
                    <span className="w-24 shrink-0 text-right text-xs tabular-nums text-secondary">
                        <span translate="no">{`${dismissed} of ${judged} dismissed`}</span>
                    </span>
                </div>
            </Tooltip>
            <div className="flex items-center gap-4 text-xs text-tertiary">
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-success" />{' '}
                    {everyone ? 'Dismissed by validation' : 'Dismissed by your bar'}
                </span>
                <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-sm bg-fill-highlight-100" /> Kept
                </span>
            </div>
        </LemonCard>
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
            <RecentReviewsSection />
        </>
    )
}

const REVIEW_SKILLS_ANCHOR = 'review-hog-skills'

function SettingsTab(): JSX.Element {
    return (
        <>
            <section className="flex flex-col gap-3">
                <p className="m-0 text-sm text-secondary">
                    Standard runs automatically on every push, following the rules below. Deep runs only when someone
                    asks for it: the Review button, the reviewhog label, or the Inbox. No Standard review runs on a pull
                    request after it had a Deep review.
                </p>
                <InstallationClaims />
                <RepositoriesPanes />
            </section>
            <FullReviewSettingsSection
                onEditSkills={() =>
                    document
                        .getElementById(REVIEW_SKILLS_ANCHOR)
                        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }
            />
            <InboxSection />
            <section className="flex flex-col gap-8 border-t border-primary pt-8">
                <PipelineSection />
                <div id={REVIEW_SKILLS_ANCHOR} className="flex flex-col gap-4 border-t border-primary pt-8">
                    <ReviewSkillsPanel />
                    <EffectivenessCard kind="perspectives" />
                    <EffectivenessCard kind="blind_spots" />
                    <ValidatorEffectivenessCard />
                </div>
            </section>
        </>
    )
}

/**
 * The "Code review" scene: ReviewHog's activity and settings page, split into an Activity tab
 * (trigger a review, recent reviews) and a Settings tab (repositories and who gets automatic Flash,
 * Full review settings, Inbox, review skills).
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
                <ReviewDetailDrawer />
            </div>
        </SceneContent>
    )
}

export default CodeReviewScene
