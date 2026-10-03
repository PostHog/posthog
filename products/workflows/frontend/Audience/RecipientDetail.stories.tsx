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
import type { MockSignature } from '~/mocks/utils'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { engagementEventsLogic } from '../engagementEventsLogic'
import { AudienceScene } from './AudienceScene'
import { audienceSceneLogic } from './audienceSceneLogic'
import type { RecipientTimelineRow } from './recipientTimelineQuery'

const CREATED_AT = '2026-09-01T10:00:00Z'

function topic(id: string, key: string, name: string, description: string): MessageCategoryApi {
    return {
        id,
        key,
        name,
        description,
        public_description: description,
        category_type: 'marketing',
        created_at: CREATED_AT,
        updated_at: CREATED_AT,
        created_by: null,
    }
}

const PRODUCT_UPDATES = topic(
    '0199c1aa-0000-7000-8000-000000000001',
    'product-updates',
    'Product updates',
    'Monthly news about new features'
)
const WEEKLY_DIGEST = topic(
    '0199c1aa-0000-7000-8000-000000000002',
    'weekly-digest',
    'Weekly digest',
    'A summary of activity in your workspace'
)

const JAMIE: RecipientApi = {
    email: 'jamie@example.com',
    all_marketing: 'NO_PREFERENCE',
    topics: { 'product-updates': 'OPTED_IN', 'weekly-digest': 'OPTED_OUT' },
    suppression: null,
    persons: [
        { uuid: '0199c1dd-0000-7000-8000-000000000002', distinct_id: 'jamie-web', name: 'Jamie Chen' },
        { uuid: '0199c1dd-0000-7000-8000-000000000003', distinct_id: 'jamie-ios', name: null },
        { uuid: '0199c1dd-0000-7000-8000-000000000004', distinct_id: 'jamie-android', name: null },
    ],
    person_count: 5,
    last_sent_at: '2026-09-30T10:00:00Z',
    preferences_updated_at: '2026-09-20T08:30:00Z',
}

const BOUNCED: RecipientApi = {
    email: 'sam.okafor+newsletters@a-very-long-company-domain.example.com',
    all_marketing: 'NO_PREFERENCE',
    topics: {},
    suppression: {
        source: 'BOUNCE',
        reason: 'Suppressed after 5 soft bounces in a row',
        suppressed_at: '2026-09-28T14:10:00Z',
    },
    persons: [],
    person_count: 0,
    last_sent_at: '2026-09-28T14:00:00Z',
    preferences_updated_at: null,
}

const RECIPIENTS_BY_EMAIL: Record<string, RecipientApi> = { [JAMIE.email]: JAMIE, [BOUNCED.email]: BOUNCED }

const TIMELINES: Record<string, RecipientTimelineRow[]> = {
    [JAMIE.email]: [
        ['$workflows_email_unsubscribed', '2026-09-30T11:00:00Z', null, null, WEEKLY_DIGEST.id],
        [
            '$workflows_email_link_clicked',
            '2026-09-30T10:05:00Z',
            'September product news',
            'https://example.com/changelog',
            null,
        ],
        ['$workflows_email_opened', '2026-09-30T10:01:00Z', 'September product news', null, null],
        ['$workflows_email_delivered', '2026-09-30T10:00:05Z', 'September product news', null, null],
        ['$workflows_email_sent', '2026-09-30T10:00:00Z', 'September product news', null, null],
    ],
    [BOUNCED.email]: [
        ['$workflows_email_bounced', '2026-09-28T14:00:10Z', 'Your weekly digest', null, null],
        ['$workflows_email_sent', '2026-09-28T14:00:00Z', 'Your weekly digest', null, null],
    ],
}

const listOrLookUpRecipients: MockSignature = ({ request }) => {
    const email = new URL(request.url).searchParams.get('email')?.toLowerCase()
    if (email === undefined) {
        return [200, { results: Object.values(RECIPIENTS_BY_EMAIL), next_cursor: null }]
    }
    const recipient = RECIPIENTS_BY_EMAIL[email]
    return recipient
        ? [200, { results: [recipient], next_cursor: null }]
        : [404, { detail: 'No recipient with this email address.' }]
}

const queryTimeline: MockSignature = async ({ request }) => {
    const { query } = ((await request.json()) as { query: { query?: string } }).query
    const email = Object.keys(TIMELINES).find((address) => query?.includes(`'${address}'`))
    return [200, { results: email ? TIMELINES[email] : [] }]
}

const meta: Meta<typeof AudienceScene> = {
    title: 'Scenes-App/Workflows/Audience/Recipient detail',
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
                '/api/projects/:team_id/messaging_categories/': toPaginatedResponse([PRODUCT_UPDATES, WEEKLY_DIGEST]),
                '/api/projects/:team_id/messaging_recipients/': listOrLookUpRecipients,
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': queryTimeline,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof AudienceScene>

// 520px is the scene width left by a 1280px window with the nav sidebar and the side panel open.
const NARROW_SCENE_WIDTH = 520

function recipientStory({
    email,
    engagementEventsCaptured,
    containerWidth,
}: {
    email: string
    engagementEventsCaptured: boolean
    containerWidth?: number
}): Story {
    return {
        render: function Render() {
            const { engagementEventsCaptured: captured } = useValues(engagementEventsLogic)
            useEffect(() => {
                router.actions.push(urls.audience())
                audienceSceneLogic.actions.openRecipient(email)
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

export const EngagementEventsOn: Story = recipientStory({ email: JAMIE.email, engagementEventsCaptured: true })
export const EngagementEventsOnNarrow: Story = recipientStory({
    email: JAMIE.email,
    engagementEventsCaptured: true,
    containerWidth: NARROW_SCENE_WIDTH,
})
export const EngagementEventsOff: Story = recipientStory({ email: JAMIE.email, engagementEventsCaptured: false })
export const EngagementEventsOffNarrow: Story = recipientStory({
    email: JAMIE.email,
    engagementEventsCaptured: false,
    containerWidth: NARROW_SCENE_WIDTH,
})
export const Suppressed: Story = recipientStory({ email: BOUNCED.email, engagementEventsCaptured: true })
export const SuppressedNarrow: Story = recipientStory({
    email: BOUNCED.email,
    engagementEventsCaptured: true,
    containerWidth: NARROW_SCENE_WIDTH,
})
export const NotFound: Story = recipientStory({ email: 'nobody@example.com', engagementEventsCaptured: true })
