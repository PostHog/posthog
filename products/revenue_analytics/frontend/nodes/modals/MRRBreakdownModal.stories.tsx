import { Meta } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { InsightLogicProps } from '~/types'

import RevenueAnalyticsMRRQueryMock from '../../__mocks__/RevenueAnalyticsMRRQuery.json'
import { MRRBreakdownModalContent } from './MRRBreakdownModal'
import { mrrBreakdownModalLogic } from './mrrBreakdownModalLogic'

const meta: Meta = {
    component: MRRBreakdownModalContent,
    title: 'Scenes-App/Revenue Analytics/MRR Breakdown Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
}
export default meta

export function MRRBreakdownModal(): JSX.Element {
    const { openModal } = useActions(mrrBreakdownModalLogic)

    useEffect(() => {
        openModal(RevenueAnalyticsMRRQueryMock.results)
    }, [openModal])

    const insightProps = { dashboardItemId: 'MRRBreakdownModal' } as InsightLogicProps
    const dataNodeLogicProps = { key: insightVizDataNodeKey(insightProps) } as DataNodeLogicProps
    const trendsDataLogicProps = insightProps as InsightLogicProps

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <BindLogic logic={trendsDataLogic} props={trendsDataLogicProps}>
                    <MRRBreakdownModalContent />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
