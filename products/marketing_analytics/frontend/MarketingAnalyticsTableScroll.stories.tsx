import type { Meta, StoryObj } from '@storybook/react'

import 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsTable/MarketingAnalyticsTableStyleOverride.scss'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { MarketingAnalyticsCell } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/shared'

const meta: Meta = {
    title: 'Scenes-App/Marketing Analytics/Table scrolling',
}
export default meta

type Story = StoryObj

export const ScrollableRows: Story = {
    render: () => (
        <div className="marketing-analytics-table-container">
            <LemonTable
                className="DataTable"
                allowContentScroll
                tableStyle={{ minWidth: '48rem' }}
                dataSource={Array.from({ length: 20 }, (_, index) => ({
                    id: index + 1,
                    campaign: `Example campaign ${index + 1}`,
                    conversions: {
                        key: 'Conversions',
                        kind: 'unit' as const,
                        value: 100 + index * 10,
                        previous: 80 + index * 10,
                        hasComparison: true,
                        changeFromPreviousPct: 25,
                        isIncreaseBad: false,
                    },
                }))}
                columns={[
                    { title: 'ID', dataIndex: 'id', width: 80 },
                    { title: 'Campaign', dataIndex: 'campaign', width: 300 },
                    { title: 'Source', render: () => <div className="p-2">example.com</div>, width: 180 },
                    {
                        title: 'Conversions',
                        dataIndex: 'conversions',
                        width: 180,
                        render: (value) => <MarketingAnalyticsCell value={value} />,
                    },
                ]}
                rowKey="id"
            />
        </div>
    ),
}
