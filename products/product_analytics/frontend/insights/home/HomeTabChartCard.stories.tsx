import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import trendsLine from '~/mocks/fixtures/api/projects/team_id/insights/trendsLine.json'

import { HomeTabChartCard } from './HomeTabChartCard'
import { getHomeTabChartOptions } from './homeTabDefaultTiles'

const meta: Meta<typeof HomeTabChartCard> = {
    component: HomeTabChartCard,
    title: 'Scenes-App/Product analytics home chart card',
    parameters: { layout: 'centered' },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': { results: trendsLine.result },
                '/api/environments/:team_id/query/:query_kind/': { results: trendsLine.result },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof HomeTabChartCard>

export const Primary: Story = {
    args: {
        option: getHomeTabChartOptions({ date_from: '-30d' }, true)[0],
        size: 'primary',
        source: 'Pageviews and screen views',
    },
    render: (args) => (
        // The chart card gets this width beside a retention card on a laptop.
        <div className="w-[420px] max-w-full">
            <HomeTabChartCard {...args} />
        </div>
    ),
}
