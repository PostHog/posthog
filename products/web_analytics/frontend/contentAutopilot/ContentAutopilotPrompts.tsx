import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { AEOPromptApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotCheckResultTag } from './ContentAutopilotCheckResultTag'
import { ContentAutopilotDraftButton } from './ContentAutopilotDraftButton'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'
import { draftableOpportunity, engineLabel, promptSearches } from './utils'

const checkTag = (prompt: AEOPromptApi, engine: string): JSX.Element => {
    const check = prompt.latest_checks.find((latest) => latest.engine === engine)
    if (!check) {
        return <span className="text-muted whitespace-nowrap">Not checked</span>
    }
    return (
        <ContentAutopilotCheckResultTag
            cited={check.cited}
            checkFailed={check.check_failed}
            position={check.target_best_position}
        />
    )
}

const PromptSearchesLine = ({ prompt }: { prompt: AEOPromptApi }): JSX.Element | null => {
    const { primary, byEngine, distinct } = promptSearches(prompt)
    if (!primary) {
        return null
    }
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    {byEngine.map(({ engine, queries }) => (
                        <div key={engine}>
                            <div className="font-semibold">{engineLabel(engine)} searched</div>
                            {queries.map((query) => (
                                <div key={query}>{query}</div>
                            ))}
                        </div>
                    ))}
                </div>
            }
        >
            <div
                className="mt-0.5 text-xs text-muted truncate max-w-120"
                tabIndex={0}
                data-attr="content-autopilot-prompt-searches"
            >
                Searched for "{primary}"{distinct > 1 ? ` +${distinct - 1} more` : ''}
            </div>
        </Tooltip>
    )
}

export const ContentAutopilotPrompts = (): JSX.Element => {
    const {
        prompts,
        promptsLoading,
        promptsError,
        promptsPage,
        promptsTopic,
        promptTopics,
        promptTopicsError,
        promptTopicsLoading,
        promptEngines,
        showArchived,
        needsImprovement,
        promptsBranded,
    } = useValues(contentAutopilotPromptsLogic)
    const {
        loadAeoPrompts,
        loadAeoPromptTopics,
        openAddPrompts,
        setNeedsImprovement,
        setPromptsPage,
        setPromptsTopic,
        setPromptsBranded,
        setShowArchived,
    } = useActions(contentAutopilotPromptsLogic)
    const { opportunityByPromptId } = useValues(contentAutopilotLogic)

    if (promptsError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }

    const count = prompts?.count ?? 0

    return (
        <section className="flex flex-col gap-3">
            <p className="m-0 text-muted max-w-3xl">
                PostHog sends each active prompt to AI assistants once a day and records whether the answer cites your
                site. Open a prompt to see the answers, edit it, or archive it.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={needsImprovement ? 'needs-improvement' : 'all'}
                    onChange={(value) => setNeedsImprovement(value === 'needs-improvement')}
                    options={[
                        { value: 'all', label: 'All prompts' },
                        {
                            value: 'needs-improvement',
                            label: 'Needs improvement',
                            tooltip: 'Prompts the AI assistants answered in the last 30 days without citing your site.',
                        },
                    ]}
                    data-attr="content-autopilot-prompts-needs-improvement"
                />
                <LemonSelect
                    size="small"
                    aria-label="Topic"
                    value={promptsTopic}
                    onChange={setPromptsTopic}
                    options={[
                        { value: null, label: 'All topics' },
                        ...promptTopics.map(({ topic, prompts: topicCount }) => ({
                            value: topic,
                            label: `${topic || 'No topic'} (${topicCount})`,
                        })),
                    ]}
                    data-attr="content-autopilot-prompts-topic-filter"
                />
                <LemonSelect
                    size="small"
                    aria-label="Branded"
                    value={promptsBranded === null ? 'all' : promptsBranded ? 'branded' : 'non_branded'}
                    onChange={(value) => setPromptsBranded(value === 'all' ? null : value === 'branded')}
                    options={[
                        { value: 'all', label: 'Branded and non-branded' },
                        {
                            value: 'branded',
                            label: 'Branded',
                            tooltip: 'Prompts that name your brand.',
                        },
                        {
                            value: 'non_branded',
                            label: 'Non-branded',
                            tooltip: "Prompts that don't name your brand.",
                        },
                    ]}
                    data-attr="content-autopilot-prompts-branded-filter"
                />
                {promptTopicsError ? (
                    <span className="flex items-center gap-1 text-danger text-sm">
                        Couldn't load topics.
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={loadAeoPromptTopics}
                            loading={promptTopicsLoading}
                            data-attr="content-autopilot-prompts-topics-retry"
                        >
                            Try again
                        </LemonButton>
                    </span>
                ) : null}
                <LemonSwitch
                    checked={showArchived}
                    onChange={setShowArchived}
                    label="Show archived"
                    bordered
                    size="small"
                    data-attr="content-autopilot-prompts-show-archived"
                />
                <div className="ml-auto flex gap-2">
                    <ContentAutopilotPromptSuggestButton size="small" />
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlusSmall />}
                        onClick={openAddPrompts}
                        data-attr="content-autopilot-prompts-add"
                    >
                        Add prompts
                    </LemonButton>
                </div>
            </div>

            {promptsError === 'failed' ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadAeoPrompts, loading: promptsLoading }}
                >
                    Couldn't load prompts. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : null}

            {prompts === null ? (
                promptsError ? null : (
                    <LemonSkeleton className="h-40 w-full" />
                )
            ) : count === 0 &&
              promptsTopic === null &&
              promptsBranded === null &&
              !showArchived &&
              !needsImprovement ? (
                <LemonCard hoverEffect={false} className="p-6 text-center">
                    <h3 className="m-0">No prompts yet</h3>
                    <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                        Add the questions your buyers ask AI assistants. Claude can suggest them from your site, or you
                        can write your own. You can also import prompts with the API (
                        <code>POST /api/projects/:project_id/aeo_prompts/bulk_import/</code>) or the PostHog MCP tools.
                    </p>
                    <div className="mt-4 flex justify-center">
                        <ContentAutopilotPromptSuggestButton type="primary" />
                    </div>
                </LemonCard>
            ) : (
                <LemonTable
                    dataSource={prompts.results}
                    rowKey="id"
                    loading={promptsLoading}
                    emptyState={
                        needsImprovement
                            ? 'No prompts need improvement. A prompt shows here when an AI assistant answered it in the last 30 days without citing your site.'
                            : promptsTopic === null
                              ? 'No prompts to show'
                              : 'No prompts have this topic'
                    }
                    pagination={{
                        controlled: true,
                        pageSize: PROMPTS_PAGE_SIZE,
                        currentPage: promptsPage,
                        entryCount: count,
                        onForward:
                            promptsPage * PROMPTS_PAGE_SIZE < count ? () => setPromptsPage(promptsPage + 1) : undefined,
                        onBackward: promptsPage > 1 ? () => setPromptsPage(promptsPage - 1) : undefined,
                    }}
                    columns={[
                        {
                            title: 'Prompt',
                            key: 'prompt',
                            render: (_, prompt) => (
                                <div className="py-2 min-w-60 break-words">
                                    <Link
                                        subtle
                                        to={urls.webAnalyticsContentAutopilotPrompt(prompt.id)}
                                        className="text-left font-semibold"
                                        data-attr="content-autopilot-prompt-open-detail"
                                    >
                                        {prompt.prompt}
                                    </Link>
                                    {prompt.branded ? (
                                        <LemonTag
                                            type="muted"
                                            size="small"
                                            className="ml-2 align-middle"
                                            title="This prompt names your brand, so answers to it almost always mention you."
                                        >
                                            Branded
                                        </LemonTag>
                                    ) : null}
                                    <PromptSearchesLine prompt={prompt} />
                                </div>
                            ),
                        },
                        {
                            title: 'Topic',
                            key: 'topic',
                            render: (_, { topic }) =>
                                topic ? (
                                    <span className="whitespace-nowrap">{topic}</span>
                                ) : (
                                    <span className="text-muted whitespace-nowrap">No topic</span>
                                ),
                        },
                        ...promptEngines.map((engine) => ({
                            title: engineLabel(engine),
                            tooltip: `Whether ${engineLabel(engine)}'s last answer linked to a page on your site.`,
                            key: `engine-${engine}`,
                            render: (_: unknown, prompt: AEOPromptApi) => checkTag(prompt, engine),
                        })),
                        {
                            title: 'Last checked',
                            key: 'last_checked_at',
                            render: (_, { last_checked_at }) =>
                                last_checked_at ? (
                                    <TZLabel time={last_checked_at} className="whitespace-nowrap" />
                                ) : (
                                    <span className="text-muted whitespace-nowrap">Never</span>
                                ),
                        },
                        {
                            key: 'draft',
                            render: (_, prompt) => {
                                const opportunity = draftableOpportunity(opportunityByPromptId, prompt)
                                return opportunity ? (
                                    <div className="whitespace-nowrap">
                                        <ContentAutopilotDraftButton opportunity={opportunity} />
                                    </div>
                                ) : null
                            },
                        },
                        {
                            title: 'Active',
                            key: 'active',
                            render: (_, { id, active, archived_at }) =>
                                archived_at ? (
                                    <LemonTag type="muted">Archived</LemonTag>
                                ) : (
                                    <ContentAutopilotPromptActiveSwitch promptId={id} active={active} />
                                ),
                        },
                    ]}
                />
            )}
        </section>
    )
}
