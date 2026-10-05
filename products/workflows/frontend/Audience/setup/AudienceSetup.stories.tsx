import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { engagementEventsLogic } from '../../engagementEventsLogic'
import { AudienceScene } from '../AudienceScene'

const CREATED_AT = '2026-09-01T10:00:00Z'

function topic(id: string, key: string, name: string, categoryType: 'marketing' | 'transactional'): MessageCategoryApi {
    return {
        id,
        key,
        name,
        category_type: categoryType,
        created_at: CREATED_AT,
        updated_at: CREATED_AT,
        created_by: null,
    }
}

const topics: MessageCategoryApi[] = [
    topic('0199c1aa-0000-7000-8000-000000000001', 'product-updates', 'Product updates', 'marketing'),
    topic('0199c1aa-0000-7000-8000-000000000002', 'weekly_digest', 'Weekly digest', 'marketing'),
    topic('0199c1aa-0000-7000-8000-000000000003', 'billing-receipts', 'Billing receipts', 'transactional'),
]

const recipients: RecipientApi[] = [
    {
        email: 'alex.rivera@example.com',
        all_marketing: 'OPTED_IN',
        topics: { 'product-updates': 'OPTED_IN' },
        suppression: null,
        persons: [],
        person_count: 0,
        last_sent_at: null,
        preferences_updated_at: '2026-09-12T08:00:00Z',
    },
]

const meta: Meta<typeof AudienceScene> = {
    title: 'Scenes-App/Workflows/Audience/Setup',
    component: AudienceScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-01T09:00:00Z',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_AUDIENCE],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof AudienceScene>

// 520px is the scene width left by a 1280px window with the nav sidebar and the side panel open.
const NARROW_SCENE_WIDTH = 520

interface SetupStoryOptions {
    path: string
    audience: { topics: MessageCategoryApi[]; recipients: RecipientApi[] }
    engagementEventsCaptured: boolean
    containerWidth?: number
}

function setupStory({ path, audience, engagementEventsCaptured, containerWidth }: SetupStoryOptions): Story {
    return {
        decorators: [
            mswDecorator({
                get: {
                    '/api/projects/:team_id/messaging_categories/': toPaginatedResponse(audience.topics),
                    '/api/projects/:team_id/messaging_recipients/': { results: audience.recipients, next_cursor: null },
                },
            }),
        ],
        render: function Render() {
            const { engagementEventsCaptured: captured } = useValues(engagementEventsLogic)
            useEffect(() => {
                router.actions.push(path)
            }, [])
            // Storybook decorators restore the default team after the story mounts, so keep reapplying it.
            useEffect(() => {
                if (captured !== engagementEventsCaptured) {
                    teamLogic.actions.loadCurrentTeamSuccess({
                        ...MOCK_DEFAULT_TEAM,
                        workflows_config: { capture_workflows_engagement_events: engagementEventsCaptured },
                    })
                }
            }, [captured])
            return (
                <div className="@container/main-content" style={{ width: containerWidth ?? '100%' }}>
                    <AudienceScene />
                </div>
            )
        },
    }
}

const emptyState: SetupStoryOptions = {
    path: urls.audience(),
    audience: { topics: [], recipients: [] },
    engagementEventsCaptured: false,
}
const setupPageWithEngagementOn: SetupStoryOptions = {
    path: urls.audienceSetup(),
    audience: { topics, recipients },
    engagementEventsCaptured: true,
}

export const EmptyState: Story = setupStory(emptyState)
export const EmptyStateNarrow: Story = setupStory({ ...emptyState, containerWidth: NARROW_SCENE_WIDTH })
export const SetupPageEngagementEventsOn: Story = setupStory(setupPageWithEngagementOn)
export const SetupPageEngagementEventsOnNarrow: Story = setupStory({
    ...setupPageWithEngagementOn,
    containerWidth: NARROW_SCENE_WIDTH,
})
