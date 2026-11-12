import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonSegmentedButton,
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

import { promptsTabFilters } from './aiVisibilityFilters'
import { ContentAutopilotCheckResult } from './ContentAutopilotCheckResult'
import { ContentAutopilotDraftButton } from './ContentAutopilotDraftButton'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { ContentAutopilotFilterBar } from './ContentAutopilotFilterBar'
import { contentAutopilotFilterBarLogic } from './contentAutopilotFilterBarLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotMentionResultTag } from './ContentAutopilotMentionResultTag'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'
import { draftableOpportunity, engineLabel, isNoSearchEngine, promptSearches } from './utils'

const checkTag = (prompt: AEOPromptApi, engine: string): JSX.Element => {
    const check = prompt.latest_checks.find((latest) => latest.engine === engine)
    if (!check) {
        return <span className="text-muted whitespace-nowrap">-</span>
    }
    if (check.mode === 'no_search') {
        return <ContentAutopilotMentionResultTag mentioned={check.mentioned} checkFailed={check.check_failed} />
    }
    return (
        <ContentAutopilotCheckResult
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
    const { prompts, promptsLoading, promptsError, promptsPage, promptEngines, showArchived, needsImprovement } =
        useValues(contentAutopilotPromptsLogic)
    const { loadAeoPrompts, openAddPrompts, setNeedsImprovement, setPromptsPage, setShowArchived } =
        useActions(contentAutopilotPromptsLogic)
    const { filters } = useValues(contentAutopilotFiltersLogic)
    // The topic list counts every prompt that is not archived, so an empty one means the project has no prompts yet.
    const { promptTopics } = useValues(contentAutopilotFilterBarLogic)
    const { opportunityByPromptId, draftingEnabled } = useValues(contentAutopilotLogic)

    if (promptsError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }

    const count = prompts?.count ?? 0

    return (
        <section className="flex flex-col gap-3">
            <ContentAutopilotFilterBar tab="prompts" filters={promptsTabFilters(needsImprovement)} />
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
                            tooltip:
                                'Prompts the AI assistants answered in the chosen date range without citing your site.',
                        },
                    ]}
                    data-attr="content-autopilot-prompts-needs-improvement"
                />
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
            ) : count === 0 && !showArchived && promptTopics?.length === 0 ? (
                <LemonCard hoverEffect={false} className="p-6 text-center">
                    <h3 className="m-0">No prompts yet</h3>
                    <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                        Add the questions your buyers ask AI assistants. PostHog can suggest them from your site, or you
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
                            ? `No prompts need improvement. A prompt shows here when an AI assistant answered it in the last ${filters.days} days without citing your site.`
                            : 'No prompts match these filters'
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
                            title: <ContentAutopilotEngineLabel engine={engine} />,
                            tooltip: isNoSearchEngine(engine)
                                ? `Whether ${engineLabel(engine)}'s last answer named your brand. It answers without searching the web, so it never links to your site.`
                                : `Whether ${engineLabel(engine)}'s last answer linked to a page on your site.`,
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
                        ...(draftingEnabled
                            ? [
                                  {
                                      key: 'draft',
                                      render: (_: unknown, prompt: AEOPromptApi) => {
                                          const opportunity = draftableOpportunity(opportunityByPromptId, prompt)
                                          return opportunity ? (
                                              <div className="whitespace-nowrap">
                                                  <ContentAutopilotDraftButton opportunity={opportunity} />
                                              </div>
                                          ) : null
                                      },
                                  },
                              ]
                            : []),
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
