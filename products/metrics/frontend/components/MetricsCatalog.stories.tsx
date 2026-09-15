import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { _MetricCatalogValuesParamsApi } from '../generated/api.schemas'
import { MetricsCatalog } from './MetricsCatalog'

const items = Array.from({ length: 40 }, (_, index) => ({
    name: `example.queue.${index}`,
    metric_type: 'gauge',
}))

const meta: Meta<typeof MetricsCatalog> = {
    title: 'Metrics/MetricsCatalog',
    component: MetricsCatalog,
    beforeEach: () => {
        const context = window.POSTHOG_APP_CONTEXT!
        const previous = context.resource_access_control
        context.resource_access_control = {
            ...previous,
            [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
        }
        return () => {
            context.resource_access_control = previous
        }
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/metrics/names/': { results: items },
            },
            post: {
                '/api/projects/:team_id/metrics/values/': async ({ request }) => {
                    const { names } = (await request.json()) as _MetricCatalogValuesParamsApi
                    return [
                        200,
                        {
                            results: names.map((name) => ({
                                name,
                                metric_type: 'gauge',
                                sparkline: [4, 6, 3, 7, 9, 5, 8, 4, 7, 10, 6, 9, 8, 5, 7, 11, 6, 8, 10, 7, 9, 6, 8, 12],
                            })),
                        },
                    ]
                },
            },
        }),
    ],
    parameters: {
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForLoadersToDisappear: false,
            waitForSelector: 'canvas[aria-label]',
        },
    },
    render: () => (
        <div className="h-[600px] w-[1200px] max-w-full overflow-auto">
            <MetricsCatalog />
        </div>
    ),
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
