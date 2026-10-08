import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    MessageCategoryApi,
    MessagePreferencesApi,
    MessageSuppressionApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { AudienceScene } from './AudienceScene'
import { AudienceTab } from './audienceSceneLogic'

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
    {
        id: '0199c1aa-0000-7000-8000-000000000004',
        key: 'monthly-product-announcements-for-engineering-and-design-teams',
        name: 'Monthly product announcements for engineering and design teams',
        description: 'Release notes for the people who build with us',
        public_description: 'What changed for builders this month',
        category_type: 'marketing',
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

function audienceTabStory(tab: AudienceTab, sceneWidth: SceneWidth): Story {
    return {
        render: function Render() {
            useEffect(() => {
                router.actions.push(urls.audience(tab))
            }, [])
            return (
                <div className={SCENE_WIDTH_CLASSES[sceneWidth]}>
                    <AudienceScene />
                </div>
            )
        },
    }
}

export const Topics: Story = audienceTabStory('topics', 'full')
export const TopicsNarrow: Story = audienceTabStory('topics', 'narrow')
export const SuppressionList: Story = audienceTabStory('suppression', 'full')
export const SuppressionListNarrow: Story = audienceTabStory('suppression', 'narrow')

export const TopicsMoreMenu: Story = {
    ...audienceTabStory('topics', 'full'),
    play: async ({ canvasElement }) => {
        const more = await waitFor(() => {
            const button = canvasElement.querySelector<HTMLElement>('[data-attr="audience-topics-more"]')
            if (!button) {
                throw new Error('The topics More menu has not rendered')
            }
            return button
        })
        fireEvent.click(more)
    },
}

export const NewTopicModal: Story = {
    ...audienceTabStory('topics', 'full'),
    play: async () => {
        await waitFor(() => {
            if (!optOutCategoriesLogic.findMounted()) {
                throw new Error('The topics list has not mounted')
            }
        })
        optOutCategoriesLogic.actions.openNewCategoryModal()
        const nameInput = await waitFor(() => {
            const input = document.querySelector<HTMLInputElement>('input[placeholder="e.g., Product updates"]')
            if (!input) {
                throw new Error('The new topic modal has not opened')
            }
            return input
        })
        fireEvent.change(nameInput, { target: { value: 'Release notes' } })
    },
}
