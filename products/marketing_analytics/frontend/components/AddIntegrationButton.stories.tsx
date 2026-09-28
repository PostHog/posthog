import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent, waitFor, within } from 'storybook/test'

import { AddIntegrationButton } from './AddIntegrationButton'
import { NEW_AD_SOURCES_SEEN_KEY } from './newAdSourcesLogic'

function SourceButtons(): JSX.Element {
    const [ready, setReady] = useState(false)
    useEffect(() => {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, has_seen_product_intro_for: {} })
        setReady(true)
    }, [])
    return (
        <div className="w-120 max-w-full min-h-40 p-4 space-y-12" data-attr="add-source-buttons">
            {ready &&
                ['Dashboard', 'Setup'].map((label) => (
                    <div key={label} className="flex items-center justify-between gap-4">
                        <span className="font-semibold">{label}</span>
                        <AddIntegrationButton />
                    </div>
                ))}
        </div>
    )
}

const meta: Meta<typeof AddIntegrationButton> = {
    title: 'Marketing Analytics/Add source',
    component: AddIntegrationButton,
    render: () => <SourceButtons />,
    decorators: [
        mswDecorator({
            patch: {
                '/api/users/@me/product_intro_seen': [200, { [NEW_AD_SOURCES_SEEN_KEY]: true }],
            },
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': [
                    200,
                    Object.fromEntries(
                        Object.entries({
                            GoogleAds: 'google-ads.png',
                            LinkedinAds: 'linkedin.png',
                            MetaAds: 'meta-ads.png',
                            TikTokAds: 'tiktok.png',
                            RedditAds: 'reddit.png',
                            BingAds: 'bing-ads.svg',
                            SnapchatAds: 'snapchat.png',
                            PinterestAds: 'pinterest_ads.png',
                            AppleSearchAds: 'apple_search_ads.png',
                            OpenAIAds: 'openai_ads.svg',
                            AmazonAds: 'amazon_ads.png',
                            BigQuery: 'bigquery.png',
                        }).map(([name, icon]) => [
                            name,
                            { name, caption: name, iconPath: `/static/services/${icon}`, fields: [] },
                        ])
                    ),
                ],
                '/api/users/@me/': [200, { ...MOCK_DEFAULT_USER, has_seen_product_intro_for: {} }],
            },
        }),
    ],
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.MARKETING_ANALYTICS_APPLE_ADS,
            FEATURE_FLAGS.MARKETING_ANALYTICS_OPENAI_ADS,
            FEATURE_FLAGS.MARKETING_ANALYTICS_AMAZON_ADS,
        ],
        testOptions: { viewport: { width: 520, height: 1024 } },
    },
}
export default meta
type Story = StoryObj<typeof AddIntegrationButton>

export const NewSources: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getAllByText('New')).toHaveLength(2))
        await userEvent.hover(canvas.getAllByText('Add source')[0])
        await within(canvasElement.ownerDocument.body).findByText('New ad sources are available')
    },
}

export const OpenMenu: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getAllByText('New')).toHaveLength(2))
        await userEvent.click(canvas.getAllByText('Add source')[0])
        await within(canvasElement.ownerDocument.body).findByText('New ad sources')
    },
}

export const DismissedEverywhere: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '[data-attr="add-source-buttons"]' } },
    play: async (context) => {
        await OpenMenu.play!(context)
        const body = within(context.canvasElement.ownerDocument.body)
        await userEvent.click(await body.findByText('Got it'))
        await waitFor(() => expect(body.queryByText('New ad sources')).not.toBeInTheDocument())
        await waitFor(() => expect(body.queryAllByText(/^new$/i)).toHaveLength(0))
        await userEvent.click(within(context.canvasElement).getByText('Dashboard'))
        await waitFor(() => expect(body.queryByText('Native integrations')).not.toBeInTheDocument())
    },
}

export const SourcesDisabled: Story = {
    parameters: { featureFlags: [] },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click((await canvas.findAllByText('Add source'))[0])
        const body = within(canvasElement.ownerDocument.body)
        await body.findByText('Native integrations')
        expect(body.queryByText('Apple Ads')).not.toBeInTheDocument()
        expect(body.queryAllByText(/^new$/i)).toHaveLength(0)
    },
}
