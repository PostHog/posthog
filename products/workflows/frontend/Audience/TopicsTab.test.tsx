import '@testing-library/jest-dom'

import { act, cleanup, render, screen, within } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MessageCategoryApi } from 'products/messaging/frontend/generated/api.schemas'

import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { OptOutScene } from '../OptOuts/OptOutScene'
import { AudienceScene } from './AudienceScene'

const PRODUCT_UPDATES: MessageCategoryApi = {
    id: '0199c1aa-0000-7000-8000-000000000001',
    key: 'product-updates',
    name: 'Product updates',
    description: 'Monthly news about new features',
    public_description: 'What we shipped this month',
    category_type: 'marketing',
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    created_by: null,
}

function TopicsTabOnWorkflows(): JSX.Element {
    return <OptOutScene />
}

function TopicsTabOnAudience(): JSX.Element {
    return <AudienceScene />
}

const TOPICS_TAB_BY_FLAG = [
    {
        flag: 'off',
        audience: false,
        TopicsTab: TopicsTabOnWorkflows,
        shown: ['Message categories', 'Marketing opt-out list', 'Import from Customer.io', 'New message category'],
        hidden: ['Topics', 'Unsubscribed from all marketing', 'New topic'],
    },
    {
        flag: 'on',
        audience: true,
        TopicsTab: TopicsTabOnAudience,
        shown: ['Unsubscribed from all marketing', 'New topic'],
        hidden: ['Message categories', 'Marketing opt-out list', 'New message category', 'Key: product-updates'],
    },
]

describe('the Topics tab', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_categories/': toPaginatedResponse([PRODUCT_UPDATES]),
                '/api/projects/:team_id/messaging_preferences/opt_outs/': toPaginatedResponse([]),
                '/api/projects/:team_id/messaging_categories/optout_sync_config/': {},
            },
        })
        initKeaTests()
        router.actions.push(urls.audience('topics'))
    })

    afterEach(() => {
        cleanup()
    })

    it.each(TOPICS_TAB_BY_FLAG)(
        'speaks the words of workflows-audience $flag',
        async ({ audience, TopicsTab, shown, hidden }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: audience })
            render(<TopicsTab />)
            await screen.findByText('Product updates')

            act(() => optOutCategoriesLogic.actions.openNewCategoryModal())

            shown.forEach((text) => expect(screen.getAllByText(text).length).toBeGreaterThan(0))
            hidden.forEach((text) => expect(screen.queryByText(text)).not.toBeInTheDocument())
        }
    )

    it('shows the topic key in the row, after its name', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)

        const name = await screen.findByText('Product updates')
        const row = name.parentElement as HTMLElement

        expect(within(row).getByText('product-updates').tagName).toBe('CODE')
    })

    it('makes New topic the one primary action and tucks the rest into a More menu', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        await screen.findByText('Product updates')

        expect(screen.getAllByText('New topic')).toHaveLength(1)
        expect(screen.queryByText('Import from Customer.io')).not.toBeInTheDocument()

        act(() => screen.getByTestId('audience-topics-more').click())

        expect(await screen.findByText('Import from Customer.io')).toBeInTheDocument()
        expect(screen.getByText('Preview preferences page')).toBeInTheDocument()
    })
})
