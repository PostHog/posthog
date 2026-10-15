import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCheckbox,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { faviconUrl, parseWebAnalyticsURL } from 'scenes/web-analytics/common'

import type { ContentAutopilotOpportunityApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { MAX_DRAFTS_PER_RUN, contentAutopilotLogic } from './contentAutopilotLogic'

const ENGINE_LABELS: Record<string, string> = {
    'claude-web-search': 'Claude',
    'openai-web-search': 'ChatGPT',
    'exa-answer': 'Exa',
}

const STATUS_TAGS: Record<ContentAutopilotOpportunityApi['status'], JSX.Element | null> = {
    new: null,
    queued: <LemonTag type="completion">Drafting</LemonTag>,
    drafted: <LemonTag type="success">Drafted</LemonTag>,
    dismissed: <LemonTag type="muted">Dismissed</LemonTag>,
}

const engineLabel = (engine: string): string => ENGINE_LABELS[engine] ?? engine

const visibilityTag = (gap: ContentAutopilotOpportunityApi['gap']): JSX.Element => {
    const answers = pluralize(gap.checks, 'answer')
    if (gap.cited_checks > 0) {
        return <LemonTag type="warning">{`Cited in ${gap.cited_checks} of ${answers}`}</LemonTag>
    }
    if (gap.mentioned_checks) {
        return <LemonTag type="highlight">{`Mentioned in ${gap.mentioned_checks} of ${answers}, not cited`}</LemonTag>
    }
    return <LemonTag type="danger">Not mentioned</LemonTag>
}

export const ContentAutopilotOpportunities = (): JSX.Element => {
    const {
        profile,
        opportunities,
        opportunitiesLoading,
        opportunitiesError,
        visibleOpportunities,
        dismissedOpportunityCount,
        showDismissedOpportunities,
        selectedOpportunityIds,
        draftDisabledReason,
        runMutationLoading,
        dismissingOpportunityId,
        opportunitySearch,
    } = useValues(contentAutopilotLogic)
    const {
        refreshOpportunities,
        toggleOpportunitySelection,
        draftOpportunities,
        dismissOpportunity,
        selectProposal,
        setShowDismissedOpportunities,
        setOpportunitySearch,
    } = useActions(contentAutopilotLogic)
    const siteName = profile?.name || profile?.domain || 'this site'

    return (
        <section className="flex flex-col gap-3">
            <p className="m-0 text-muted max-w-3xl">
                Questions AI assistants answered without citing {siteName}, most promising first. Pick up to{' '}
                {MAX_DRAFTS_PER_RUN} and draft them.
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search questions"
                    value={opportunitySearch}
                    onChange={setOpportunitySearch}
                    className="w-72"
                    data-attr="content-autopilot-search-opportunities"
                />
                <div className="flex flex-wrap items-center gap-2">
                    {dismissedOpportunityCount > 0 ? (
                        <LemonSwitch
                            checked={showDismissedOpportunities}
                            onChange={setShowDismissedOpportunities}
                            label={`Show dismissed (${dismissedOpportunityCount})`}
                            bordered
                            size="small"
                        />
                    ) : null}
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={refreshOpportunities}
                        loading={opportunitiesLoading}
                        data-attr="content-autopilot-refresh-opportunities"
                    >
                        Refresh
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={draftOpportunities}
                        loading={runMutationLoading}
                        disabledReason={draftDisabledReason}
                        data-attr="content-autopilot-draft-opportunities"
                    >
                        {selectedOpportunityIds.length > 0
                            ? `Draft ${pluralize(selectedOpportunityIds.length, 'page')}`
                            : 'Draft selected'}
                    </LemonButton>
                </div>
            </div>

            {opportunitiesError ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: refreshOpportunities, loading: opportunitiesLoading }}
                >
                    {opportunities === null
                        ? "Couldn't load opportunities."
                        : "Couldn't refresh opportunities. The list below may be out of date."}{' '}
                    {opportunitiesError}
                </LemonBanner>
            ) : null}
            {opportunities === null ? (
                opportunitiesError ? null : (
                    <LemonSkeleton className="h-40 w-full" />
                )
            ) : visibleOpportunities.length === 0 ? (
                <LemonCard hoverEffect={false} className="p-6 text-center">
                    {opportunitySearch.trim() ? (
                        <p className="m-0 text-muted">No questions match your search.</p>
                    ) : dismissedOpportunityCount > 0 ? (
                        <>
                            <h3 className="m-0">All questions are dismissed</h3>
                            <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                                Turn on "Show dismissed" to see them again, or refresh to check for new citation gaps.
                            </p>
                        </>
                    ) : (
                        <>
                            <h3 className="m-0">No citation gaps found</h3>
                            <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                                Opportunities appear when AI citation checks show an assistant answering a tracked
                                question without citing {siteName}. If checks haven't run for this project yet, there's
                                nothing to show.
                            </p>
                        </>
                    )}
                </LemonCard>
            ) : (
                <LemonTable
                    dataSource={visibleOpportunities}
                    rowKey="id"
                    pagination={{ pageSize: 25 }}
                    columns={[
                        {
                            key: 'select',
                            width: 0,
                            render: (_, opportunity) => (
                                <LemonCheckbox
                                    checked={selectedOpportunityIds.includes(opportunity.id)}
                                    onChange={() => toggleOpportunitySelection(opportunity.id)}
                                    disabledReason={
                                        opportunity.status === 'queued' || opportunity.status === 'dismissed'
                                            ? 'This opportunity is not available to draft'
                                            : undefined
                                    }
                                    aria-label={`Select ${opportunity.title}`}
                                />
                            ),
                        },
                        {
                            title: 'Question',
                            key: 'title',
                            render: (_, opportunity) => (
                                <div className="flex flex-wrap items-center gap-2 py-2 min-w-60">
                                    <span className="font-semibold">{opportunity.title}</span>
                                    {STATUS_TAGS[opportunity.status]}
                                </div>
                            ),
                        },
                        {
                            title: 'In AI answers',
                            key: 'visibility',
                            render: (_, { gap }) => (
                                <div className="whitespace-nowrap">
                                    {visibilityTag(gap)}
                                    {gap.engines_not_citing.length > 0 ? (
                                        <div className="text-xs text-muted mt-1">
                                            Not cited by {gap.engines_not_citing.map(engineLabel).join(', ')}
                                        </div>
                                    ) : null}
                                </div>
                            ),
                        },
                        {
                            title: 'Cited instead',
                            key: 'competitors',
                            render: (_, { gap }) =>
                                gap.competitor_domains.length > 0 ? (
                                    <div className="flex flex-col gap-1">
                                        {gap.competitor_domains.slice(0, 3).map((domain) => (
                                            <span key={domain} className="flex items-center gap-1 text-sm">
                                                <img
                                                    src={faviconUrl(domain)}
                                                    width={16}
                                                    height={16}
                                                    alt=""
                                                    className="shrink-0"
                                                    onError={(e) => (e.currentTarget.style.display = 'none')}
                                                />
                                                <span className="truncate">{domain}</span>
                                            </span>
                                        ))}
                                    </div>
                                ) : (
                                    <span className="text-sm text-muted">No sources cited</span>
                                ),
                        },
                        {
                            title: 'Suggested fix',
                            key: 'recommendation',
                            render: (_, opportunity) =>
                                opportunity.recommended_type === 'page_improvement' && opportunity.target_url ? (
                                    <span className="text-sm">
                                        Update{' '}
                                        <Link to={opportunity.target_url} target="_blank">
                                            {parseWebAnalyticsURL(opportunity.target_url).pathname ??
                                                opportunity.target_url}
                                        </Link>
                                    </span>
                                ) : (
                                    <span className="text-sm text-muted">Decided when drafting</span>
                                ),
                        },
                        {
                            key: 'actions',
                            render: (_, opportunity) => (
                                <div className="flex flex-wrap justify-end gap-1">
                                    {opportunity.proposal_id && opportunity.status === 'drafted' ? (
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            onClick={() => selectProposal(opportunity.proposal_id)}
                                            data-attr="content-autopilot-review-opportunity-draft"
                                        >
                                            Review draft
                                        </LemonButton>
                                    ) : null}
                                    {opportunity.status !== 'dismissed' ? (
                                        <LemonButton
                                            size="small"
                                            type="tertiary"
                                            onClick={() => dismissOpportunity(opportunity.id)}
                                            loading={dismissingOpportunityId === opportunity.id}
                                            disabledReason={
                                                opportunity.status === 'queued'
                                                    ? 'Wait for the draft to finish'
                                                    : dismissingOpportunityId &&
                                                        dismissingOpportunityId !== opportunity.id
                                                      ? 'Wait for the other question to finish dismissing'
                                                      : undefined
                                            }
                                            data-attr="content-autopilot-dismiss-opportunity"
                                        >
                                            Dismiss
                                        </LemonButton>
                                    ) : null}
                                </div>
                            ),
                        },
                    ]}
                />
            )}
        </section>
    )
}
