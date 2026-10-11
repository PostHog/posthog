import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import { SearchConsoleSource } from './SearchConsoleSource'
import { SourceSetupPanel } from './SourceSetupPanel'

const meta: Meta<typeof SourceSetupPanel> = {
    title: 'Scenes-App/Marketing Analytics/Source setup panel',
    component: SourceSetupPanel,
    parameters: { layout: 'padded', mockDate: '2026-10-07', testOptions: { waitForLoadersToDisappear: false } },
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
export const Checking: Story = { args: { state: 'checking' } }
export const Scanning: Story = { args: { state: 'scanning', footer } }
export const DetectedPlatforms: Story = { args: { state: 'suggestions', suggestions, footer } }
export const NoDetectedPlatforms: Story = { args: { state: 'empty', footer } }
export const ScanFailed: Story = { args: { state: 'error', onRetry: () => {}, footer } }
export const Connected: Story = {
    args: {
        state: 'waiting',
        connections: [
            {
                id: 'demo-google',
                name: 'Google Ads',
                sourceType: 'GoogleAds',
                status: 'Connected',
                detail: 'Waiting for the first sync to finish.',
            },
        ],
        suggestions: [suggestions[1]],
        footer: <LemonButton>Browse integrations</LemonButton>,
    },
}
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
        footer: <LemonButton>Browse integrations</LemonButton>,
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

export const MissingConnectionAction: Story = {
    args: { state: 'suggestions', suggestions: [{ ...suggestions[0], apply: null }], footer },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        expect(canvas.getByText('Google Ads')).toBeVisible()
        expect(canvas.queryByRole('link', { name: 'Connect' })).not.toBeInTheDocument()
    },
}

export const DismissedSuggestions: Story = {
    args: { state: 'dismissed', onRestore: () => {}, footer },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        expect(canvas.getByRole('button', { name: 'Restore suggestions' })).toBeVisible()
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
