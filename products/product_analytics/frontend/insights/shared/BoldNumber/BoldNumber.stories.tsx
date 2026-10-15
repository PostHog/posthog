import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsNumber from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import __trendsNumberCompareNullPrevious from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumberCompareNullPrevious.json'
import __trendsNumberEmpty from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumberEmpty.json'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { BoldNumber, HogQLBoldNumber } from './BoldNumber'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/BoldNumber',
    component: BoldNumber,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-11',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.BoldNumber__value',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsNumber as any} />,
}

export const EmptyResult: Story = {
    render: () => <InsightVizStory insight={__trendsNumberEmpty as any} />,
    parameters: { testOptions: { waitForSelector: '[data-attr="insight-empty-state"]' } },
}

export const CompareNullPrevious: Story = {
    render: () => <InsightVizStory insight={__trendsNumberCompareNullPrevious as any} />,
}

export const SqlChartFormatting: Story = {
    render: () => (
        <div className="w-96 h-48">
            <BindLogic
                logic={dataVisualizationLogic}
                props={{
                    key: 'sql-bold-number-formatting',
                    dataNodeCollectionId: 'sql-bold-number-formatting',
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: { kind: NodeKind.HogQLQuery, query: 'SELECT 87654.25 AS amount' },
                        display: ChartDisplayType.BoldNumber,
                        chartSettings: {
                            yAxis: [
                                {
                                    column: 'amount',
                                    settings: {
                                        formatting: {
                                            style: 'number',
                                            prefix: '$',
                                            suffix: ' total',
                                            decimalPlaces: 2,
                                        },
                                    },
                                },
                            ],
                        },
                    },
                    cachedResults: { columns: ['amount'], types: [['amount', 'Float64']], results: [[87654.25]] },
                }}
            >
                <HogQLBoldNumber />
            </BindLogic>
        </div>
    ),
}
