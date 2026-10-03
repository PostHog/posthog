import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'
import type { MessageCategoryApi } from 'products/messaging/frontend/generated/api.schemas'

import { NewCategoryButton } from '../OptOuts/NewCategoryButton'
import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { OptOutScene } from '../OptOuts/OptOutScene'
import { optOutSceneLogic } from '../OptOuts/optOutSceneLogic'
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
    return (
        <>
            <NewCategoryButton />
            <OptOutScene />
        </>
    )
}

function TopicsTabOnAudience(): JSX.Element {
    return <AudienceScene />
}

const TOPICS_TAB_BY_FLAG = [
    {
        flag: 'off',
        audience: false,
        TopicsTab: TopicsTabOnWorkflows,
        modalTitle: 'New message category',
        shown: ['Message categories', 'Marketing opt-out list', 'Opt-out date', 'New category'],
        hidden: ['Topics', 'Unsubscribed from all marketing', 'Unsubscribed on', 'New topic'],
    },
    {
        flag: 'on',
        audience: true,
        TopicsTab: TopicsTabOnAudience,
        modalTitle: 'New topic',
        shown: ['Unsubscribed from all marketing', 'Unsubscribed on'],
        hidden: ['Message categories', 'Marketing opt-out list', 'Opt-out date', 'New message category'],
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
        jest.restoreAllMocks()
    })

    it.each(TOPICS_TAB_BY_FLAG)(
        'speaks the words of workflows-audience $flag',
        async ({ audience, TopicsTab, modalTitle, shown, hidden }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: audience })
            render(<TopicsTab />)
            await screen.findByText('Product updates')

            act(() => optOutCategoriesLogic.actions.openNewCategoryModal())

            expect(within(await screen.findByRole('dialog')).getByText(modalTitle)).toBeInTheDocument()
            shown.forEach((text) => expect(screen.getAllByText(text).length).toBeGreaterThan(0))
            hidden.forEach((text) => expect(screen.queryByText(text)).not.toBeInTheDocument())
        }
    )

    it('shows the topic key in the row after its name, and not again when the row opens', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        const name = await screen.findByText('Product updates')

        act(() => name.click())

        expect(within(name.parentElement as HTMLElement).getByText('product-updates').tagName).toBe('CODE')
        expect(await screen.findByText('Public description: What we shipped this month')).toBeInTheDocument()
        expect(screen.queryByText(/Key:/)).not.toBeInTheDocument()
    })

    it('fills the key from the name typed into the new topic modal', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        await screen.findByText('Product updates')
        act(() => optOutCategoriesLogic.actions.openNewCategoryModal())

        fireEvent.change(await screen.findByPlaceholderText('e.g., Product updates'), {
            target: { value: 'Release notes' },
        })

        expect(screen.getByPlaceholderText('e.g., product-updates')).toHaveValue('release-notes')
    })

    it.each([
        { state: 'with topics', topics: [PRODUCT_UPDATES] },
        { state: 'with no topics yet', topics: [] },
    ])('makes New topic the one primary action and tucks the rest into a More menu $state', async ({ topics }) => {
        useMocks({ get: { '/api/projects/:team_id/messaging_categories/': toPaginatedResponse(topics) } })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        await waitFor(() => expect(optOutCategoriesLogic.values.categoriesLoading).toBe(false))

        const moreTrigger = screen.getByTestId('audience-topics-more')
        expect(screen.getAllByText('New topic')).toHaveLength(1)
        expect(within(moreTrigger.closest('section') as HTMLElement).getByText('New topic')).toBeInTheDocument()
        expect(screen.queryByText('Import from Customer.io')).not.toBeInTheDocument()

        act(() => moreTrigger.click())
        act(() => screen.getByText('Import from Customer.io').click())

        expect(within(await screen.findByRole('dialog')).getByText('Customer.io integration')).toBeInTheDocument()
    })

    it("leaves the More menu free while a recipient's preferences page loads", async () => {
        jest.spyOn(messagingApi, 'messagingPreferencesGenerateLinkCreate').mockReturnValue(new Promise(() => {}))
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        await screen.findByText('Product updates')

        act(() => optOutSceneLogic.actions.openPreferencesPage('jamie@example.com'))

        await waitFor(() => expect(optOutSceneLogic.values.preferencesUrlLoading).toBe(true))
        expect(screen.getByTestId('audience-topics-more')).not.toHaveAttribute('aria-disabled', 'true')
    })

    it("keeps the More menu busy while its preview loads, even after a recipient's page opens", async () => {
        jest.spyOn(messagingApi, 'messagingPreferencesGenerateLinkCreate').mockImplementation((_, body) =>
            body?.recipient === 'jamie@example.com'
                ? Promise.resolve({ preferences_url: 'https://example.com/preferences/jamie' })
                : new Promise(() => {})
        )
        jest.spyOn(window, 'open').mockReturnValue(null)
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        await screen.findByText('Product updates')

        act(() => optOutSceneLogic.actions.openPreferencesPage())
        await expectLogic(optOutSceneLogic, () =>
            optOutSceneLogic.actions.openPreferencesPage('jamie@example.com')
        ).toDispatchActions(['openPreferencesPageSuccess'])

        expect(screen.getByTestId('audience-topics-more')).toHaveAttribute('aria-disabled', 'true')
    })

    it.each([
        {
            outcome: 'opens',
            generateLink: () => Promise.resolve({ preferences_url: 'https://example.com/preferences/abc' }),
            openedTabs: [['https://example.com/preferences/abc', '_blank']],
        },
        {
            outcome: 'fails',
            generateLink: () => Promise.reject(new Error('Server error')),
            openedTabs: [],
        },
    ])('frees the More menu once the preferences page preview $outcome', async ({ generateLink, openedTabs }) => {
        jest.spyOn(messagingApi, 'messagingPreferencesGenerateLinkCreate').mockImplementation(generateLink)
        const openTab = jest.spyOn(window, 'open').mockReturnValue(null)
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: true })
        render(<AudienceScene />)
        await screen.findByText('Product updates')
        const moreTrigger = screen.getByTestId('audience-topics-more')

        act(() => moreTrigger.click())
        act(() => screen.getByText('Preview preferences page').click())

        expect(moreTrigger).toHaveAttribute('aria-disabled', 'true')
        await waitFor(() => expect(optOutSceneLogic.values.preferencesUrlLoading).toBe(false))
        expect(moreTrigger).not.toHaveAttribute('aria-disabled', 'true')
        expect(openTab.mock.calls).toEqual(openedTabs)
    })
})
