import { useActions } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { userInterviewsLogic } from './userInterviewsLogic'

export const scene: SceneExport = {
    component: UserInterviews,
    logic: userInterviewsLogic,
}

// Matches the UserInterviewTopic model shape from the backend
export interface TopicStub {
    id: string
    topic: string
    interviewee_cohort: number | null
    interviewee_emails: string[]
    interviewee_distinct_ids: string[]
    agent_context: string
    questions: string[]
    created_at: string
    created_by: { first_name: string; email: string } | null
    // UI-only stub fields (not in the model yet — faked for now)
    status: 'draft' | 'active' | 'completed'
    cohort_name: string | null
    total_targeted: number
    total_responded: number
}

export const FAKE_TOPICS: TopicStub[] = [
    {
        id: 'topic_1',
        topic: 'Understanding why new users drop off during onboarding',
        interviewee_cohort: 42,
        interviewee_emails: ['alice@acme.co', 'bob@startup.io', 'carol@bigcorp.com'],
        interviewee_distinct_ids: [],
        agent_context:
            'Be warm and conversational. These are new users who signed up in the last 30 days — some may not have completed setup.',
        questions: [
            'Tell me about your experience signing up for PostHog.',
            'Was there a point where you felt stuck or confused?',
            'What did you expect to happen after creating your account?',
            'If you could change one thing about getting started, what would it be?',
        ],
        created_at: '2026-05-10T14:30:00Z',
        created_by: { first_name: 'Kim', email: 'kim@posthog.com' },
        status: 'active',
        cohort_name: 'New signups last 30 days',
        total_targeted: 48,
        total_responded: 12,
    },
    {
        id: 'topic_2',
        topic: 'Do power users know about dashboard templates?',
        interviewee_cohort: 87,
        interviewee_emails: [],
        interviewee_distinct_ids: [],
        agent_context: 'Keep it short — 10 minute call max. Skip pleasantries.',
        questions: [
            'How do you typically create dashboards?',
            'Are you aware of dashboard templates?',
            'Would pre-built templates save you time?',
        ],
        created_at: '2026-05-08T10:00:00Z',
        created_by: { first_name: 'James', email: 'james@posthog.com' },
        status: 'active',
        cohort_name: 'Power users (10+ insights)',
        total_targeted: 25,
        total_responded: 8,
    },
    {
        id: 'topic_3',
        topic: 'Why did users on the Teams plan cancel in April?',
        interviewee_cohort: 15,
        interviewee_emails: ['cto@ecommerce.com', 'lead@agency.co'],
        interviewee_distinct_ids: [],
        agent_context:
            "Be empathetic — these users just churned. Don't pitch or promise features. Focus on understanding their reasons.",
        questions: [
            'What originally brought you to PostHog?',
            'What led to your decision to cancel?',
            'Is there anything that would have changed your mind?',
        ],
        created_at: '2026-04-20T09:15:00Z',
        created_by: { first_name: 'Kim', email: 'kim@posthog.com' },
        status: 'completed',
        cohort_name: 'Churned Teams plan — April',
        total_targeted: 15,
        total_responded: 6,
    },
    {
        id: 'topic_4',
        topic: 'What prevents teams from enabling session replay?',
        interviewee_cohort: null,
        interviewee_emails: [],
        interviewee_distinct_ids: [],
        agent_context: '',
        questions: [],
        created_at: '2026-05-12T16:00:00Z',
        created_by: { first_name: 'Li', email: 'li@posthog.com' },
        status: 'draft',
        cohort_name: null,
        total_targeted: 0,
        total_responded: 0,
    },
]

function StatusTag({ status }: { status: TopicStub['status'] }): JSX.Element {
    const config = {
        draft: { type: 'default' as const, label: 'Draft' },
        active: { type: 'success' as const, label: 'Active' },
        completed: { type: 'completion' as const, label: 'Completed' },
    }
    const { type, label } = config[status]
    return <LemonTag type={type}>{label}</LemonTag>
}

const NEW_TOPIC_PROMPT = `!I want to set up a new user research topic. Help me through the process:

1. First, let's figure out what I want to learn — what feature, behavior, or question I want to research.
2. Then, help me identify the right users to interview — find or create a cohort, or I can provide emails.
3. Draft interview questions based on the topic.
4. Set up the outreach workflow to email each user with their unique interview link.
5. Once I confirm, trigger the emails — I'll track responses in User research.

Let's start — ask me what I want to learn about.`

export function UserInterviews(): JSX.Element {
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
                columns={[
                    {
                        title: 'Topic',
                        key: 'topic',
                        render: (_, row: TopicStub) => (
                            <LemonTableLink title={row.topic} to={urls.userInterview(row.id)} />
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 100,
                        render: (_, row: TopicStub) => <StatusTag status={row.status} />,
                    },
                    {
                        title: 'Targeting',
                        key: 'targeting',
                        render: (_, row: TopicStub) => (
                            <span className="text-sm">
                                {row.cohort_name || (row.interviewee_emails.length > 0 ? 'Email list' : 'Not set')}
                            </span>
                        ),
                    },
                    {
                        title: 'Responses',
                        key: 'responses',
                        width: 120,
                        render: (_, row: TopicStub) => (
                            <span>
                                {row.total_responded} / {row.total_targeted}
                            </span>
                        ),
                    },
                    {
                        title: 'Questions',
                        key: 'questions',
                        width: 100,
                        render: (_, row: TopicStub) => (
                            <span className="text-muted">
                                {row.questions.length} question{row.questions.length !== 1 ? 's' : ''}
                            </span>
                        ),
                    },
                    {
                        title: 'Owner',
                        key: 'owner',
                        width: 100,
                        render: (_, row: TopicStub) => <span>{row.created_by?.first_name || '—'}</span>,
                    },
                ]}
                dataSource={FAKE_TOPICS}
                rowKey="id"
                loadingSkeletonRows={5}
            />
        </SceneContent>
    )
}
