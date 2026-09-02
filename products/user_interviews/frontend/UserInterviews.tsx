import { useActions, useValues } from 'kea'

import { IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { userInterviewsEmptyState } from './emptyState/userInterviewsEmptyState'
import type { UserInterviewSearchResultApi, UserInterviewTopicApi } from './generated/api.schemas'
import { NEW_TOPIC_PROMPT, NEW_TOPIC_SUGGESTIONS } from './newTopicMaxTool'
import { userInterviewsLogic } from './userInterviewsLogic'

export const scene: SceneExport = {
    component: UserInterviews,
    logic: userInterviewsLogic,
    productKey: ProductKey.USER_INTERVIEWS,
    emptyState: userInterviewsEmptyState,
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
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { setSearchQuery } = useActions(userInterviewsLogic)
    const hasSearch = searchQuery.trim().length > 0

    const { openMax } = useMaxTool({
        identifier: 'create_user_interview_topic',
        context: {},
        initialMaxPrompt: NEW_TOPIC_PROMPT,
        suggestions: NEW_TOPIC_SUGGESTIONS,
        // `openMax` is null only when the tool is inactive, so the button's disabledReason
        // needs this to fire on an instance without PostHog AI.
        active: isMaxAvailable,
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
