import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    FilterClearItem,
    FilterMenuTrigger,
    FilterSubMenu,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { AEOPromptApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { promptsTabFilters } from './aiVisibilityFilters'
import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotCheckResult } from './ContentAutopilotCheckResult'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { ContentAutopilotFilterBar } from './ContentAutopilotFilterBar'
import { contentAutopilotFilterBarLogic } from './contentAutopilotFilterBarLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { ContentAutopilotMentionResultTag } from './ContentAutopilotMentionResultTag'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'
import { engineLabel, isNoSearchEngine, promptSearches } from './utils'

const MutedCell = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
        {children}
    </Text>
)

const checkTag = (prompt: AEOPromptApi, engine: string): JSX.Element => {
    const check = prompt.latest_checks.find((latest) => latest.engine === engine)
    if (!check) {
        return <MutedCell>-</MutedCell>
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
        <Tooltip>
            <TooltipTrigger
                render={
                    <Text
                        size="xs"
                        variant="muted"
                        render={<div className="m-0 mt-0.5 max-w-120 truncate" />}
                        tabIndex={0}
                        data-attr="content-autopilot-prompt-searches"
                    />
                }
            >
                Searched for "{primary}"{distinct > 1 ? ` +${distinct - 1} more` : ''}
            </TooltipTrigger>
            <TooltipContent className="max-w-80">
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
            </TooltipContent>
        </Tooltip>
    )
}

const LOADING_ROWS = 6

const PromptLimitCount = (): JSX.Element | null => {
    const { setupContext } = useValues(contentAutopilotPromptsLogic)
    if (!setupContext) {
        return null
    }
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span className="whitespace-nowrap" />}
                        tabIndex={0}
                        data-attr="content-autopilot-prompt-limit"
                    />
                }
            >
                {`${setupContext.active_prompts} of ${setupContext.max_active_prompts} prompts tracked`}
            </TooltipTrigger>
            <TooltipContent>
                Each tracked prompt is checked by every enabled AI assistant on its schedule.
            </TooltipContent>
        </Tooltip>
    )
}

type PromptsView = 'all' | 'needs-improvement'

/** The list's own filters. The date, engine, topic and branded filters sit in the shared filter bar beside it. */
const PromptsFilterMenu = (): JSX.Element => {
    const { needsImprovement, showArchived } = useValues(contentAutopilotPromptsLogic)
    const { setNeedsImprovement, setShowArchived } = useActions(contentAutopilotPromptsLogic)
    const view: PromptsView = needsImprovement ? 'needs-improvement' : 'all'

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={needsImprovement || showArchived} dataAttr="content-autopilot-prompts-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterSubMenu
                    label="Show"
                    value={needsImprovement ? 'Needs improvement' : 'All prompts'}
                    active={needsImprovement}
                    dataAttr="content-autopilot-prompts-needs-improvement"
                >
                    <DropdownMenuRadioGroup
                        value={view}
                        onValueChange={(next) => setNeedsImprovement((next as PromptsView) === 'needs-improvement')}
                    >
                        <DropdownMenuRadioItem value="all">All prompts</DropdownMenuRadioItem>
                        <DropdownMenuRadioItem
                            value="needs-improvement"
                            tooltip="Prompts the AI assistants answered in the chosen date range without citing your site."
                        >
                            Needs improvement
                        </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                </FilterSubMenu>
                <DropdownMenuCheckboxItem
                    checked={showArchived}
                    closeOnClick={false}
                    onCheckedChange={(checked) => setShowArchived(checked)}
                    data-attr="content-autopilot-prompts-show-archived"
                >
                    Show archived
                </DropdownMenuCheckboxItem>
                <FilterClearItem
                    active={needsImprovement || showArchived}
                    onClear={() => {
                        if (needsImprovement) {
                            setNeedsImprovement(false)
                        }
                        if (showArchived) {
                            setShowArchived(false)
                        }
                    }}
                    dataAttr="content-autopilot-prompts-filters-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export const ContentAutopilotPrompts = (): JSX.Element => {
    const { prompts, promptsLoading, promptsError, promptsPage, promptEngines, showArchived, needsImprovement } =
        useValues(contentAutopilotPromptsLogic)
    const { loadAeoPrompts, setNeedsImprovement, setPromptsPage, setShowArchived } =
        useActions(contentAutopilotPromptsLogic)
    // The topic list counts every prompt that is not archived, so an empty one means the project has no prompts yet.
    const { promptTopics, promptTopicsError } = useValues(contentAutopilotFilterBarLogic)
    const { filters } = useValues(contentAutopilotFiltersLogic)
    const { setTopic } = useActions(contentAutopilotFiltersLogic)

    if (promptsError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }

    const count = prompts?.count ?? 0
    const firstRun = prompts !== null && count === 0 && !showArchived && promptTopics?.length === 0
    // With no prompts on the page, the topics decide between the first-run state and no matches, so wait for them.
    const waitingForTopics = prompts !== null && count === 0 && promptTopics === null && !promptTopicsError
    const narrowed = needsImprovement || showArchived || filters.topic !== null
    const clearFilters = (): void => {
        if (needsImprovement) {
            setNeedsImprovement(false)
        }
        if (showArchived) {
            setShowArchived(false)
        }
        if (filters.topic !== null) {
            setTopic(null, 'prompts')
        }
    }

    return (
        <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <ContentAutopilotFilterBar tab="prompts" filters={promptsTabFilters(needsImprovement)} />
                <PromptsFilterMenu />
                <div className="ml-auto flex flex-wrap items-center gap-2">
                    <PromptLimitCount />
                </div>
            </div>
            <Text size="xs" variant="muted" className="m-0 max-w-3xl">
                PostHog sends each active prompt to AI assistants on each engine's schedule and records whether the
                answer cites your site. Open a prompt to see the answers, edit it, or archive it.
            </Text>

            {promptsError === 'failed' ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadAeoPrompts, loading: promptsLoading }}
                >
                    Couldn't load prompts. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : null}

            {prompts === null && promptsError ? null : firstRun ? (
                <Empty className="rounded-md border p-6">
                    <EmptyHeader className="max-w-xl">
                        <EmptyTitle>No prompts yet</EmptyTitle>
                        <EmptyDescription>
                            Add the questions your buyers ask AI assistants. PostHog can suggest them from your site, or
                            you can write your own. You can also import prompts with the API (
                            <code>POST /api/projects/:project_id/aeo_prompts/bulk_import/</code>) or the PostHog MCP
                            tools.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <ContentAutopilotPromptSuggestButton type="primary" />
                    </EmptyContent>
                </Empty>
            ) : (
                <AiVisibilityTable
                    dataSource={prompts?.results ?? []}
                    rowKey="id"
                    // Before the first page arrives, placeholder rows hold the table's shape.
                    loading={promptsLoading || prompts === null || waitingForTopics}
                    loadingSkeletonRows={LOADING_ROWS}
                    emptyState={
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>
                                    {needsImprovement
                                        ? 'No prompts need improvement'
                                        : 'No prompts match these filters'}
                                </EmptyTitle>
                                {needsImprovement ? (
                                    <EmptyDescription>
                                        A prompt shows here when an AI assistant answered it in the selected date range
                                        without citing your site.
                                    </EmptyDescription>
                                ) : null}
                            </EmptyHeader>
                            {narrowed ? (
                                <EmptyContent>
                                    <Button
                                        variant="outline"
                                        onClick={clearFilters}
                                        data-attr="content-autopilot-prompts-empty-clear-filters"
                                    >
                                        Clear filters
                                    </Button>
                                </EmptyContent>
                            ) : null}
                        </Empty>
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
                                    {/* A prompt is a sentence, so the link wraps instead of truncating like a name. */}
                                    <Button
                                        variant="link-foreground"
                                        size="inline"
                                        nativeButton={false}
                                        render={
                                            <LinkPrimitive to={urls.webAnalyticsContentAutopilotPrompt(prompt.id)} />
                                        }
                                        className="whitespace-normal text-left font-semibold"
                                        data-attr="content-autopilot-prompt-open-detail"
                                    >
                                        {prompt.prompt}
                                    </Button>
                                    {prompt.branded ? (
                                        <AiVisibilityTag
                                            type="muted"
                                            className="ml-2 align-middle"
                                            title="This prompt names your brand, so answers to it almost always mention you."
                                        >
                                            Branded
                                        </AiVisibilityTag>
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
                                    <MutedCell>No topic</MutedCell>
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
                                    <MutedCell>Never</MutedCell>
                                ),
                        },
                        {
                            title: 'Active',
                            key: 'active',
                            render: (_, { id, active, archived_at }) =>
                                archived_at ? (
                                    <AiVisibilityTag type="muted">Archived</AiVisibilityTag>
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
