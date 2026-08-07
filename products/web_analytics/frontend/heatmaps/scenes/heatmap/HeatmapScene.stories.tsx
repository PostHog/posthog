import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// updated_at is the render's server-side start, and the scene shows elapsed time relative to it, so
// keep it fresh on each fetch rather than a fixed past date (which would render an absurd elapsed).
const makeGeneratingSaved = (): Record<string, unknown> => ({
    id: 100,
    short_id: 'hm_gen',
    name: 'Generating…',
    url: 'https://example.com',
    data_url: 'https://example.com',
    target_widths: [768, 1024],
    type: 'screenshot',
    status: 'processing',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    exception: null,
})

const failedSaved = {
    id: 102,
    short_id: 'hm_failed',
    name: 'Failed render',
    url: 'https://example.com',
    data_url: 'https://example.com',
    target_widths: [1024],
    type: 'screenshot',
    status: 'failed',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    exception:
        "Screenshot generation timed out before it finished. This can happen when the page is slow to load or can't be reached. Try regenerating, or use an iframe or session recording background instead.",
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmap',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmap('hm_gen'),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/saved/hm_gen/': () => [200, makeGeneratingSaved()],
                '/api/projects/:team_id/heatmap_screenshots/:id/content/': () => [202, makeGeneratingSaved()],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Generating: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const GenerationFailed: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_failed'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/saved/hm_failed/': () => [200, failedSaved],
            },
        }),
    ],
}

const makeIframeSaved = (): Record<string, unknown> => ({
    id: 101,
    short_id: 'hm_iframe',
    name: 'Iframe example.com',
    url: `${window.location.origin}/mock-page.html`,
    data_url: `${window.location.origin}/mock-page.html`,
    target_widths: [],
    type: 'iframe',
    status: 'completed',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-03T00:00:00Z',
    updated_at: '2024-01-03T00:00:00Z',
    exception: null,
})

export const IframeExample: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_iframe'),
        testOptions: {
            // Wait for heatmap canvas to be ready with data loaded
            waitForSelector: '.heatmaps-ready',
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/saved/hm_iframe/': () => [200, makeIframeSaved()],
                '/api/projects/:team_id/heatmaps/': () => [
                    200,
                    {
                        results: [
                            { pointer_relative_x: 0.4, pointer_target_fixed: false, pointer_y: 355, count: 85 },
                            { pointer_relative_x: 0.7, pointer_target_fixed: false, pointer_y: 24, count: 32 },
                            { pointer_relative_x: 0.77, pointer_target_fixed: false, pointer_y: 24, count: 28 },
                            { pointer_relative_x: 0.84, pointer_target_fixed: false, pointer_y: 24, count: 15 },
                            { pointer_relative_x: 0.91, pointer_target_fixed: false, pointer_y: 24, count: 12 },
                            { pointer_relative_x: 0.1, pointer_target_fixed: false, pointer_y: 24, count: 18 },
                            { pointer_relative_x: 0.17, pointer_target_fixed: false, pointer_y: 1150, count: 22 },
                            { pointer_relative_x: 0.5, pointer_target_fixed: false, pointer_y: 1150, count: 19 },
                            { pointer_relative_x: 0.83, pointer_target_fixed: false, pointer_y: 1150, count: 14 },
                        ],
                        count: 9,
                        next: null,
                        previous: null,
                    },
                ],
            },
        }),
    ],
}

export const New: Story = {
    parameters: {
        pageUrl: urls.heatmap('new'),
    },
}
