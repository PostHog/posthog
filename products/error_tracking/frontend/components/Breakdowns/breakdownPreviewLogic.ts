import { connect, kea, key, path, props, selectors } from 'kea'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import type { breakdownPreviewLogicType } from './breakdownPreviewLogicType'

export interface BreakdownSinglePropertyStat {
    label: string
    count: number
}

export interface BreakdownPreviewLogicProps {
    dataNodeLogicProps: DataNodeLogicProps
}

export const breakdownPreviewLogic = kea<breakdownPreviewLogicType>([
    path(['products', 'error_tracking', 'components', 'Breakdowns', 'breakdownPreviewLogic']),
    props({} as BreakdownPreviewLogicProps),
    key((props) => props.dataNodeLogicProps.key || 'default'),
    connect((props: BreakdownPreviewLogicProps) => ({
        values: [dataNodeLogic(props.dataNodeLogicProps), ['response', 'responseLoading']],
    })),
    selectors(() => ({
        properties: [
            (s) => [s.response],
            (response): BreakdownSinglePropertyStat[] => {
                const breakdownData: BreakdownSinglePropertyStat[] = []

                if (response && 'results' in response && Array.isArray(response.results)) {
                    response.results.forEach((series: any) => {
                        if (series.data && series.label) {
                            breakdownData.push({
                                label: series.label,
                                count: series.aggregated_value,
                            })
                        }
                    })
                }

                return breakdownData
            },
        ],
        totalCount: [
            (s) => [s.properties],
            (properties): number => {
                return properties.reduce((sum, item) => sum + item.count, 0)
            },
        ],
    })),
])
