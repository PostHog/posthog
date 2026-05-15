import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import type { UserInterviewTopicApi } from './generated/api.schemas'
import { userInterviewsLogic } from './userInterviewsLogic'

export const scene: SceneExport = {
    component: UserInterviews,
    logic: userInterviewsLogic,
}

function targetingLabel(topic: UserInterviewTopicApi): string {
    const emailCount = topic.interviewee_emails?.length || 0
    const distinctIdCount = topic.interviewee_distinct_ids?.length || 0
    const hasCohort = topic.interviewee_cohort != null
    const parts: string[] = []
    if (hasCohort) {
        parts.push(`Cohort #${topic.interviewee_cohort}`)
    }
    if (emailCount > 0) {
        parts.push(`${emailCount} email${emailCount !== 1 ? 's' : ''}`)
    }
    if (distinctIdCount > 0) {
        parts.push(`${distinctIdCount} ID${distinctIdCount !== 1 ? 's' : ''}`)
    }
    return parts.length > 0 ? parts.join(' + ') : 'Not set'
}

const NEW_TOPIC_PROMPT = `!I want to set up a new user research topic. Help me through the process:

1. First, let's figure out what I want to learn — what feature, behavior, or question I want to research.
2. Then, help me identify the right users to interview — find or create a cohort, or I can provide emails.
3. Draft interview questions based on the topic.
4. Set up the outreach workflow to email each user with their unique interview link.
5. Once I confirm, trigger the emails — I'll track responses in User research.

Let's start — ask me what I want to learn about.`

export function UserInterviews(): JSX.Element {
    const { topics, topicsLoading } = useValues(userInterviewsLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.UserInterviews].name}
                description="Run AI-powered voice research campaigns. Target a cohort, set a topic, and let the AI handle the interviews."
                resourceType={{
                    type: sceneConfigurations[Scene.UserInterviews].iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconSparkles />}
                        data-attr="new-topic"
                        onClick={() => openSidePanel(SidePanelTab.Max, NEW_TOPIC_PROMPT)}
                    >
                        New topic
                    </LemonButton>
                }
            />
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
        </SceneContent>
    )
}
