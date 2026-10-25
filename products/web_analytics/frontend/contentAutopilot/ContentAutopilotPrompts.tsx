import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonCard,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { AEOPromptApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotCheckResultTag } from './ContentAutopilotCheckResultTag'
import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptDetail } from './ContentAutopilotPromptDetail'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { engineLabel } from './utils'

const checkTag = (prompt: AEOPromptApi, engine: string): JSX.Element => {
    const check = prompt.latest_checks.find((latest) => latest.engine === engine)
    if (!check) {
        return <span className="text-muted whitespace-nowrap">Not checked</span>
    }
    return <ContentAutopilotCheckResultTag cited={check.cited} checkFailed={check.check_failed} />
}

export const ContentAutopilotPrompts = (): JSX.Element => {
    const {
        prompts,
        promptsLoading,
        promptsError,
        promptsPage,
        promptsTopic,
        promptTopics,
        promptEngines,
        showArchived,
    } = useValues(contentAutopilotPromptsLogic)
    const { loadAeoPrompts, setPromptsPage, setPromptsTopic, setShowArchived } =
        useActions(contentAutopilotPromptsLogic)
    const { openPromptDetail } = useActions(contentAutopilotPromptDetailLogic)

    if (promptsError === 'forbidden') {
        return (
            <LemonCard hoverEffect={false} className="p-6 text-center">
                <h3 className="m-0">AI citation tracking is not turned on</h3>
                <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                    This project doesn't have access to prompt tracking yet. Ask PostHog support to turn on AI citation
                    tracking for it.
                </p>
            </LemonCard>
        )
    }

    const count = prompts?.count ?? 0

    return (
        <section className="flex flex-col gap-3">
            <p className="m-0 text-muted max-w-3xl">
                The questions PostHog asks AI assistants every day, and whether each one cited your site the last time
                it ran.
            </p>
            <p className="m-0 text-muted max-w-3xl">
                You can view tracked prompts, turn them on or off, and archive them here. To add prompts or change their
                text, use the API (<code>POST /api/projects/:project_id/aeo_prompts/bulk_import/</code>) or the PostHog
                MCP tools. A text change adds a new version of the prompt.
            </p>
            <div className="flex flex-wrap items-center gap-2">
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
                <LemonSwitch
                    checked={showArchived}
                    onChange={setShowArchived}
                    label="Show archived"
                    bordered
                    size="small"
                    data-attr="content-autopilot-prompts-show-archived"
                />
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
            ) : count === 0 && promptsTopic === null && !showArchived ? (
                <LemonCard hoverEffect={false} className="p-6 text-center">
                    <h3 className="m-0">No prompts yet</h3>
                    <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                        Add prompts with the API (<code>POST /api/projects/:project_id/aeo_prompts/bulk_import/</code>)
                        or the PostHog MCP tools. They're checked against AI assistants on the next daily run.
                    </p>
                </LemonCard>
            ) : (
                <LemonTable
                    dataSource={prompts.results}
                    rowKey="id"
                    loading={promptsLoading}
                    emptyState={promptsTopic === null ? 'No prompts to show' : 'No prompts have this topic'}
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
                                        onClick={() => openPromptDetail(prompt.id)}
                                        className="text-left font-semibold"
                                        data-attr="content-autopilot-prompt-open-detail"
                                    >
                                        {prompt.prompt}
                                    </Link>
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
            <ContentAutopilotPromptDetail />
        </section>
    )
}
