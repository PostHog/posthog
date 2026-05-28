import { useActions, useValues } from 'kea'

import { IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { cn } from 'lib/utils/css-classes'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { UserInterviewSearchResultApi, UserInterviewTopicApi } from './generated/api.schemas'
import { userInterviewsLogic } from './userInterviewsLogic'

export const scene: SceneExport = {
    component: UserInterviews,
    logic: userInterviewsLogic,
}

function targetingLabel(topic: UserInterviewTopicApi): string {
    const emailCount = topic.interviewee_emails?.length || 0
    const distinctIdCount = topic.interviewee_distinct_ids?.length || 0
    const parts: string[] = []
    if (emailCount > 0) {
        parts.push(`${emailCount} email${emailCount !== 1 ? 's' : ''}`)
    }
    if (distinctIdCount > 0) {
        parts.push(`${distinctIdCount} ID${distinctIdCount !== 1 ? 's' : ''}`)
    }
    return parts.length > 0 ? parts.join(' + ') : 'Not set'
}

const NEW_TOPIC_PROMPT = `!I want to set up a new user research topic. Help me work through:
1. What I want to learn — the feature, behavior, or question to research.
2. Who to interview — let me give you emails or distinct IDs, or help me pick from a cohort.
3. The interview questions — 3-6 open-ended, conversational prompts in a sensible order.
Then create the topic using the create_user_interview_topic tool. Don't try to send emails or generate links yourself — once the topic exists I'll do that from the topic page.`

const NEW_TOPIC_SUGGESTIONS = [
    'Interview recent signups about their onboarding experience',
    'Talk to power users about what they wish the product did better',
    'Interview customers who churned in the last 30 days',
    'Research how teams are using dashboards day-to-day',
]

function SearchResultCard({ result }: { result: UserInterviewSearchResultApi }): JSX.Element {
    const target = result.topic_id
        ? urls.userInterviewResponse(result.topic_id, encodeURIComponent(result.interviewee_identifier))
        : null
    const card = (
        <div className="border rounded p-3 hover:bg-accent-highlight-secondary">
            <div className="flex items-center gap-2 mb-1 text-sm">
                <LemonTag type="muted">{result.document_type}</LemonTag>
                <span className="text-muted">{Math.round(result.similarity * 100)}% match</span>
                <span className="text-muted">·</span>
                <span>{result.interviewee_identifier}</span>
            </div>
            <p className="text-sm">{result.content_snippet}</p>
        </div>
    )
    return target ? (
        <Link to={target} className="block">
            {card}
        </Link>
    ) : (
        card
    )
}

function SearchResults({
    results,
    loading,
}: {
    results: UserInterviewSearchResultApi[]
    loading: boolean
}): JSX.Element {
    if (results.length === 0) {
        return <p className="text-muted">{loading ? 'Searching…' : 'No matching responses yet.'}</p>
    }
    return (
        <div className={cn('flex flex-col gap-2 transition-opacity', loading && 'opacity-50')}>
            {results.map((r) => (
                <SearchResultCard key={`${r.interview_id}-${r.document_type}`} result={r} />
            ))}
        </div>
    )
}

export function UserInterviews(): JSX.Element {
    const { topics, topicsLoading, searchQuery, searchResults, searchResultsLoading } = useValues(userInterviewsLogic)
    const { setSearchQuery } = useActions(userInterviewsLogic)
    const hasSearch = searchQuery.trim().length > 0

    const { openMax } = useMaxTool({
        identifier: 'create_user_interview_topic',
        context: {},
        initialMaxPrompt: NEW_TOPIC_PROMPT,
        suggestions: NEW_TOPIC_SUGGESTIONS,
    })

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.UserInterviews].name}
                description="Run AI-powered voice research campaigns. Target an audience, set a topic, and let the AI handle the interviews."
                resourceType={{
                    type: sceneConfigurations[Scene.UserInterviews].iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconSparkles />}
                        data-attr="new-topic"
                        onClick={() => openMax?.()}
                        disabledReason={openMax ? undefined : 'PostHog AI is unavailable here'}
                    >
                        New topic
                    </LemonButton>
                }
            />
            <LemonInput
                type="search"
                prefix={<IconSearch />}
                placeholder="Search what users said across all interviews — e.g. 'problems with the taxonomic filter'"
                value={searchQuery}
                onChange={setSearchQuery}
                allowClear
                fullWidth
                data-attr="user-interviews-search"
            />
            {hasSearch ? (
                <SearchResults results={searchResults} loading={searchResultsLoading} />
            ) : (
                <LemonTable
                    loading={topicsLoading}
                    columns={[
                        {
                            title: 'Topic',
                            key: 'topic',
                            render: (_, row: UserInterviewTopicApi) => (
                                <LemonTableLink title={row.topic} to={urls.userInterview(row.id)} />
                            ),
                        },
                        {
                            title: 'Targeting',
                            key: 'targeting',
                            render: (_, row: UserInterviewTopicApi) => (
                                <span className="text-sm">{targetingLabel(row)}</span>
                            ),
                        },
                        {
                            title: 'Questions',
                            key: 'questions',
                            width: 100,
                            render: (_, row: UserInterviewTopicApi) => {
                                const count = row.questions?.length || 0
                                return (
                                    <span className="text-muted">
                                        {count} question{count !== 1 ? 's' : ''}
                                    </span>
                                )
                            },
                        },
                        {
                            title: 'Created',
                            key: 'created_at',
                            render: (_, row: UserInterviewTopicApi) => (
                                <span className="text-muted whitespace-nowrap">{row.created_at?.split('T')[0]}</span>
                            ),
                            sorter: (a, b) => (a.created_at || '').localeCompare(b.created_at || ''),
                        },
                        {
                            title: 'Created by',
                            key: 'created_by',
                            render: (_, row: UserInterviewTopicApi) => (
                                <span>{row.created_by?.first_name || row.created_by?.email || '—'}</span>
                            ),
                        },
                    ]}
                    dataSource={topics}
                    rowKey="id"
                    loadingSkeletonRows={5}
                    emptyState="No topics yet. Click 'New topic' to get started with PostHog AI."
                />
            )}
        </SceneContent>
    )
}
