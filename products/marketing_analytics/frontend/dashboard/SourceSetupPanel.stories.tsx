import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import { SearchConsoleSource } from './SearchConsoleSource'
import { SourceSetupPanel } from './SourceSetupPanel'

const meta: Meta<typeof SourceSetupPanel> = {
    title: 'Scenes-App/Marketing Analytics/Source setup panel',
    component: SourceSetupPanel,
    parameters: { layout: 'padded', mockDate: '2026-10-07', testOptions: { waitForLoadersToDisappear: false } },
    // The expanded groups persist in localStorage, so without this a story inherits what an earlier run left open.
    beforeEach: () => localStorage.removeItem('products.marketingAnalytics.sourceConnectionGroups.setup.expansion'),
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': () => [
                    200,
                    {
                        GoogleAds: { iconPath: '/static/services/google-ads.png' },
                        BingAds: { iconPath: '/static/services/bing-ads.svg' },
                        MetaAds: { iconPath: '/static/services/meta-ads.png' },
                        GoogleSearchConsole: { iconPath: '/static/services/google-search-console.svg' },
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof SourceSetupPanel>
const suggestions = ['GoogleAds', 'MetaAds'].map((kind) => ({
    id: `connect_source:${kind}`,
    kind: 'connect_source' as const,
    integration: kind,
    severity: 'warning' as const,
    confidence: 1,
    source: 'deterministic' as const,
    title: kind === 'GoogleAds' ? 'Connect Google Ads' : 'Connect Meta Ads',
    evidence:
        kind === 'GoogleAds'
            ? 'Events contain Google Ads campaign tracking in utm_source and gclid.'
            : 'Events contain Meta Ads campaign tracking in utm_source and fbclid.',
    unlocks: ['cost' as const],
    apply: { op: 'open_source_wizard' as const, kind },
    also_recommended: [],
    safe_to_batch: false,
    rank_score: 1,
    deep_link: null,
    docs_url: null,
    spend_at_risk: 0,
    event_volume: 12,
}))
const footer = <LemonButton>Browse integrations</LemonButton>
export const DetectedPlatforms: Story = { args: { state: 'suggestions', suggestions, footer } }
export const Syncing: Story = {
    args: {
        state: 'waiting',
        connections: [
            {
                id: 'demo-google',
                name: 'Google Ads',
                sourceType: 'GoogleAds',
                status: 'Syncing',
                detail: 'Your first import is running. Spend data will appear when it finishes.',
            },
        ],
        suggestions: [suggestions[1]],
        footer,
    },
}
export const Narrow: Story = {
    args: DetectedPlatforms.args,
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}

export const DetectedPlatformsWithSearchConsole: Story = {
    decorators: [
        (Story) => (
            <>
                <Story />
                <SearchConsoleSource />
            </>
        ),
    ],
    args: DetectedPlatforms.args,
    parameters: { featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS] },
}

const quillDecorators: Decorator[] = [
    (Story) => (
        <QuillSurfaceContext.Provider value={true}>
            <div className="w-160">
                <Story />
            </div>
        </QuillSurfaceContext.Provider>
    ),
]

export const DetectedPlatformsWithSearchConsoleQuill: Story = {
    decorators: [
        (Story) => (
            <>
                <Story />
                <SearchConsoleSource />
            </>
        ),
        ...quillDecorators,
    ],
    args: { ...DetectedPlatforms.args, footer: <Button variant="outline">Browse integrations</Button> },
    parameters: {
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: '[data-attr="marketing-search-console-extra"]' },
    },
}

export const MissingConnectionAction: Story = {
    args: { state: 'suggestions', suggestions: [{ ...suggestions[0], apply: null }], footer },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        expect(await canvas.findByText('Google Ads')).toBeVisible()
        expect(canvas.queryByRole('link', { name: 'Connect' })).not.toBeInTheDocument()
    },
}

export const DismissedSuggestions: Story = {
    args: { state: 'dismissed', onRestore: () => {}, footer },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        expect(await canvas.findByRole('button', { name: 'Restore suggestions' })).toBeVisible()
        expect(canvas.queryByText(/No ad platforms were detected/)).not.toBeInTheDocument()
    },
}
export const PausedImport: Story = {
    args: {
        state: 'waiting',
        connections: [
            {
                id: 'example-paused',
                name: 'Google Ads',
                sourceType: 'GoogleAds',
                status: 'Needs attention',
                detail: 'The import is paused or canceled. Open setup to resume it.',
            },
        ],
        footer,
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        expect(await canvas.findByText('Some connections need attention')).toBeVisible()
        expect(canvas.getByRole('link', { name: /Manage source/ })).toBeVisible()
    },
}

export const GroupedConnectionErrors: Story = {
    args: {
        state: 'waiting',
        compact: true,
        connections: [
            {
                id: 'example-google-one',
                name: 'Example campaigns',
                sourceType: 'GoogleAds',
                status: 'Needs attention',
                detail: 'campaign: import disabled. Enable this table in the source’s Schemas tab. campaign_overview_stats: sync failed. Review the error in the source’s Schemas tab.',
            },
            {
                id: 'example-google-two',
                name: 'Example search',
                sourceType: 'GoogleAds',
                status: 'Sync failed',
                detail: 'campaign_overview_stats: sync failed. Review the error in the source’s Schemas tab.',
            },
            {
                id: 'example-tiktok',
                name: 'Example video',
                sourceType: 'TikTokAds',
                status: 'Needs attention',
                detail: 'campaign_report: import disabled. Enable this table in the source’s Schemas tab.',
            },
        ],
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        expect(await canvas.findByText('Example campaigns')).toBeVisible()
        expect(canvas.getByText('Example search')).toBeVisible()
        expect(canvas.getByText(/campaign: import disabled.*campaign_overview_stats: sync failed/)).toBeVisible()
        expect(canvas.getByText('2 connections')).toBeVisible()
        expect(canvas.getAllByRole('link', { name: /Manage source/ })[0]).toHaveAttribute(
            'href',
            expect.stringContaining('managed-example-google-one')
        )
        expect(canvas.getByRole('button', { name: /TikTok Ads/ })).toHaveAttribute('aria-expanded', 'true')
        expect(canvas.getByText('Example video')).toBeVisible()
    },
}

export const GroupedConnectionErrorsQuill: Story = {
    args: GroupedConnectionErrors.args,
    decorators: quillDecorators,
    parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Example campaigns')).toBeVisible()
        await expect(canvas.getByText('Example search')).toBeVisible()
        await expect(canvas.getByText('2 connections')).toBeVisible()
        await expect(canvas.getAllByRole('link', { name: /Manage source/ })[0]).toHaveAttribute(
            'href',
            expect.stringContaining('managed-example-google-one')
        )
        await expect(canvas.getByRole('button', { name: /TikTok Ads/ })).toHaveAttribute('aria-expanded', 'true')
        await expect(canvas.getByText('Example video')).toBeVisible()
    },
}

export const NarrowConnectionErrors: Story = {
    ...GroupedConnectionErrors,
    decorators: [
        (Story) => (
            <div className="w-full max-w-lg">
                <Story />
            </div>
        ),
    ],
}
