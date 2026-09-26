import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import retentionFixture from '~/mocks/fixtures/api/projects/team_id/insights/retention.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { InsightLogicProps, InsightShortId } from '~/types'

import { RetentionContainer } from '../RetentionContainer'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/RetentionTable',
    component: RetentionContainer,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

let uniqueNode = 0

// Enough cohorts and intervals that the table outgrows a half-width tile on both axes.
const manyCohortsResult = Array.from({ length: 14 }, (_, cohortIndex) => ({
    label: `Day ${cohortIndex}`,
    date: `2023-07-${String(cohortIndex + 1).padStart(2, '0')}T00:00:00Z`,
    values: Array.from({ length: 14 - cohortIndex }, (_, interval) => ({
        count: Math.round(1024 * Math.exp(-interval / 4)),
        people: [],
    })),
    people_url: '',
}))

const manyCohortsFixture: any = { ...retentionFixture, result: manyCohortsResult }

function renderRetentionTable(): JSX.Element {
    const [dashboardItemId] = useState(() => `RetentionTableStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight = { ...manyCohortsFixture, short_id: dashboardItemId }

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                {/* A half-width dashboard tile: too narrow for the intervals, too short for the cohorts. */}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ width: 420, height: 300, display: 'flex', flexDirection: 'column' }}>
                    <RetentionContainer inCardView vizSpecificOptions={{ hideLineGraph: true }} />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const NarrowTile: Story = {
    render: () => renderRetentionTable(),
}
