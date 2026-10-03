import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import type { MockSignature } from '~/mocks/utils'

import type {
    MessageCategoryApi,
    MessagePreferencesApi,
    MessageSuppressionApi,
    RecipientApi,
    RecipientPageApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { AudienceScene } from './AudienceScene'
import { AudienceTab } from './audienceSceneLogic'
import { recipientsLogic } from './recipientsLogic'

const CREATED_AT = '2026-09-01T10:00:00Z'

const topics: MessageCategoryApi[] = [
    {
        id: '0199c1aa-0000-7000-8000-000000000001',
        key: 'product-updates',
        name: 'Product updates',
        description: 'Monthly news about new features',
        public_description: 'What we shipped this month',
        category_type: 'marketing',
        created_at: CREATED_AT,
        updated_at: CREATED_AT,
        created_by: null,
    },
    {
        id: '0199c1aa-0000-7000-8000-000000000002',
        key: 'weekly-digest',
        name: 'Weekly digest',
        description: 'A summary of activity in your workspace',
        public_description: 'Your week at a glance',
        category_type: 'marketing',
        created_at: CREATED_AT,
        updated_at: CREATED_AT,
        created_by: null,
    },
    {
        id: '0199c1aa-0000-7000-8000-000000000003',
        key: 'billing-receipts',
        name: 'Billing receipts',
        description: 'Invoices and payment confirmations',
        public_description: 'Receipts for your payments',
        category_type: 'transactional',
        created_at: CREATED_AT,
        updated_at: CREATED_AT,
        created_by: null,
    },
]

const unsubscribedFromAllMarketing: MessagePreferencesApi[] = ['jamie', 'alex', 'sam', 'robin'].map((name, index) => ({
    id: `0199c1bb-0000-7000-8000-00000000000${index}`,
    identifier: `${name}@example.com`,
    updated_at: `2026-09-2${index}T08:30:00Z`,
    preferences: { $all: 'OPTED_OUT' },
}))

const suppressions: MessageSuppressionApi[] = [
    {
        id: '0199c1cc-0000-7000-8000-000000000001',
        identifier: 'bounced@example.com',
        source: 'BOUNCE',
        reason: 'Suppressed after 5 soft bounces in a row',
        transient_bounce_count: 5,
        last_bounce_at: '2026-09-28T14:10:00Z',
        last_bounce_diagnostic: '550 5.1.1 The email account does not exist',
        suppressed: true,
        suppressed_at: '2026-09-28T14:10:00Z',
        created_at: '2026-09-20T09:00:00Z',
        updated_at: '2026-09-28T14:10:00Z',
    },
    {
        id: '0199c1cc-0000-7000-8000-000000000002',
        identifier: 'spam-report@example.com',
        source: 'COMPLAINT',
        reason: 'The recipient marked a message as spam',
        transient_bounce_count: 0,
        last_bounce_at: null,
        last_bounce_diagnostic: null,
        suppressed: true,
        suppressed_at: '2026-09-25T11:00:00Z',
        created_at: '2026-09-25T11:00:00Z',
        updated_at: '2026-09-25T11:00:00Z',
    },
    {
        id: '0199c1cc-0000-7000-8000-000000000003',
        identifier: 'do-not-email@example.com',
        source: 'MANUAL',
        reason: null,
        transient_bounce_count: 0,
        last_bounce_at: null,
        last_bounce_diagnostic: null,
        suppressed: true,
        suppressed_at: '2026-09-18T16:45:00Z',
        created_at: '2026-09-18T16:45:00Z',
        updated_at: '2026-09-18T16:45:00Z',
    },
]

const NO_ACTIVITY: Pick<RecipientApi, 'topics' | 'suppression' | 'persons' | 'person_count' | 'last_sent_at'> = {
    topics: {},
    suppression: null,
    persons: [],
    person_count: 0,
    last_sent_at: null,
}

const recipients: RecipientApi[] = [
    {
        ...NO_ACTIVITY,
        email: 'alex.rivera@example.com',
        all_marketing: 'OPTED_IN',
        topics: { 'product-updates': 'OPTED_IN', 'weekly-digest': 'OPTED_OUT' },
        persons: [{ uuid: '0199c1dd-0000-7000-8000-000000000001', distinct_id: 'alex-r', name: 'Alex Rivera' }],
        person_count: 1,
        last_sent_at: '2026-09-29T15:20:00Z',
        preferences_updated_at: '2026-09-12T08:00:00Z',
    },
    {
        ...NO_ACTIVITY,
        email: 'bounced@example.com',
        all_marketing: 'NO_PREFERENCE',
        suppression: {
            source: 'BOUNCE',
            reason: 'Suppressed after 5 soft bounces in a row',
            suppressed_at: '2026-09-28T14:10:00Z',
        },
        preferences_updated_at: null,
    },
    {
        ...NO_ACTIVITY,
        email: 'jamie@example.com',
        all_marketing: 'OPTED_OUT',
        persons: [
            { uuid: '0199c1dd-0000-7000-8000-000000000002', distinct_id: 'jamie-web', name: 'Jamie Chen' },
            { uuid: '0199c1dd-0000-7000-8000-000000000003', distinct_id: 'jamie-ios', name: null },
        ],
        person_count: 2,
        last_sent_at: '2026-09-03T09:00:00Z',
        preferences_updated_at: '2026-09-20T08:30:00Z',
    },
    {
        ...NO_ACTIVITY,
        email: 'sam.okafor+newsletters@a-very-long-company-domain.example.com',
        all_marketing: 'NO_PREFERENCE',
        topics: { 'weekly-digest': 'OPTED_IN', 'quarterly-roadmap-and-release-notes-for-admins': 'OPTED_OUT' },
        persons: [{ uuid: '0199c1dd-0000-7000-8000-000000000004', distinct_id: 'sam-okafor', name: null }],
        person_count: 1,
        last_sent_at: '2026-09-30T18:45:00Z',
        preferences_updated_at: '2026-08-30T10:00:00Z',
    },
    {
        ...NO_ACTIVITY,
        email: 'taylor@example.com',
        all_marketing: 'NO_PREFERENCE',
        persons: [{ uuid: '0199c1dd-0000-7000-8000-000000000005', distinct_id: 'taylor-1', name: 'Taylor Brooks' }],
        person_count: 1,
        preferences_updated_at: null,
    },
]

function recipientsResponse(page: RecipientPageApi | [number, unknown]): MockSignature {
    return () => (Array.isArray(page) ? page : [200, page])
}

const meta: Meta<typeof AudienceScene> = {
    title: 'Scenes-App/Workflows/Audience',
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
                '/api/projects/:team_id/messaging_categories/': toPaginatedResponse(topics),
                '/api/projects/:team_id/messaging_preferences/opt_outs/':
                    toPaginatedResponse(unsubscribedFromAllMarketing),
                '/api/projects/:team_id/messaging_suppressions/suppressions/': toPaginatedResponse(suppressions),
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 1342 },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof AudienceScene>

type SceneWidth = 'full' | 'narrow'

const SCENE_WIDTH_CLASSES: Record<SceneWidth, string> = {
    full: 'w-full',
    // 520px is the scene width left by a 1280px window with the nav sidebar and the side panel open.
    narrow: 'w-[520px]',
}

interface AudienceStoryOptions {
    sceneWidth?: SceneWidth
    recipientsPage?: RecipientPageApi | [number, unknown]
    search?: string
}

function audienceTabStory(
    tab: AudienceTab,
    {
        sceneWidth = 'full',
        recipientsPage = { results: recipients, next_cursor: 'after-taylor' },
        search,
    }: AudienceStoryOptions = {}
): Story {
    return {
        decorators: [
            mswDecorator({
                get: { '/api/projects/:team_id/messaging_recipients/': recipientsResponse(recipientsPage) },
            }),
        ],
        render: function Render() {
            useEffect(() => {
                router.actions.push(urls.audience(tab))
                if (search) {
                    recipientsLogic.actions.setSearch(search)
                }
            }, [])
            return (
                <div className={SCENE_WIDTH_CLASSES[sceneWidth]}>
                    <AudienceScene />
                </div>
            )
        },
    }
}

export const Recipients: Story = audienceTabStory('recipients')
export const RecipientsNarrow: Story = audienceTabStory('recipients', { sceneWidth: 'narrow' })
export const RecipientsEmpty: Story = audienceTabStory('recipients', {
    recipientsPage: { results: [], next_cursor: null },
})
export const RecipientsNoMatch: Story = {
    ...audienceTabStory('recipients', { recipientsPage: { results: [], next_cursor: null }, search: 'nobody@' }),
    parameters: { testOptions: { waitForSelector: '[data-attr="audience-recipients-clear-search"]' } },
}
export const RecipientsError: Story = audienceTabStory('recipients', {
    recipientsPage: [500, { detail: 'The query took too long.' }],
})
export const RecipientsAccessDenied: Story = audienceTabStory('recipients', {
    recipientsPage: [403, { code: 'permission_denied', detail: 'You need hog_flow viewer access to view recipients.' }],
})
export const Topics: Story = audienceTabStory('topics')
export const TopicsNarrow: Story = audienceTabStory('topics', { sceneWidth: 'narrow' })
export const SuppressionList: Story = audienceTabStory('suppression')
export const SuppressionListNarrow: Story = audienceTabStory('suppression', { sceneWidth: 'narrow' })
