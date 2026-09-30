import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'

import { HeatmapScreenshotCookieSettings } from './HeatmapScreenshotCookieSettings'

const meta: Meta<typeof HeatmapScreenshotCookieSettings> = {
    title: 'Web Analytics/Heatmaps/Screenshot cookie settings',
    component: HeatmapScreenshotCookieSettings,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/heatmap_screenshot/settings/': {
                    allowed_hostnames: ['example.com', 'www.example.com'],
                    has_secret: true,
                    cookie_delivery_enabled: true,
                },
            },
            patch: {
                '/api/projects/:id/heatmap_screenshot/settings/': async ({ request }) => [
                    200,
                    { ...((await request.json()) as object), has_secret: true, cookie_delivery_enabled: true },
                ],
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof HeatmapScreenshotCookieSettings>

export const Admin: Story = {
    render: () => {
        const { loadCurrentTeamSuccess } = useActions(teamLogic)
        useEffect(() => {
            loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                app_urls: ['https://example.com', 'https://www.example.com', 'https://docs.example.com'],
                heatmaps_screenshot_secret: 'phh_synthetic_example',
            })
        }, [loadCurrentTeamSuccess])
        return <HeatmapScreenshotCookieSettings />
    },
}

export const Editor: Story = {
    render: () => {
        const { loadCurrentTeamSuccess } = useActions(teamLogic)
        useEffect(() => {
            loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                effective_membership_level: OrganizationMembershipLevel.Member,
                heatmaps_screenshot_secret: null,
            })
        }, [loadCurrentTeamSuccess])
        return <HeatmapScreenshotCookieSettings />
    },
}

export const NeedsApproval: Story = {
    ...Admin,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/heatmap_screenshot/settings/': {
                    allowed_hostnames: [],
                    has_secret: true,
                    cookie_delivery_enabled: true,
                },
            },
        }),
    ],
}

export const Narrow: Story = {
    ...Admin,
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}

export const DeliveryDisabled: Story = {
    ...Admin,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/heatmap_screenshot/settings/': {
                    allowed_hostnames: ['example.com'],
                    has_secret: true,
                    cookie_delivery_enabled: false,
                },
            },
        }),
    ],
}
