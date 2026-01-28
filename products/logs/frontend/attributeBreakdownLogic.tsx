import { connect, kea, key, path, props, selectors } from 'kea'

import { PropertyFilterType } from '~/types'

import type { attributeBreakdownLogicType } from './attributeBreakdownLogicType'
import { logsSceneLogic } from './logsSceneLogic'

export interface AttributeBreakdownLogicProps {
    attribute: string
    type: PropertyFilterType
    tabId: string
}

export const attributeBreakdownLogic = kea<attributeBreakdownLogicType>([
    props({} as AttributeBreakdownLogicProps),
    key((props) => `${props.tabId}-${props.type}-${props.attribute}`),
    path((key) => ['products', 'logs', 'frontend', 'logsAttributeBreakdownsLogic', key]),

    connect((props: AttributeBreakdownLogicProps) => ({
        values: [logsSceneLogic({ tabId: props.tabId }), ['logs']],
    })),

    selectors(({ props }) => ({
        logCount: [(s) => [s.logs], (logs): number => logs.length],
        attributeValues: [
            (s) => [s.logs],
            (logs): string[] => {
                let attributesKey: 'attributes' | 'resource_attributes' = 'attributes'
                if (props.type === PropertyFilterType.LogResourceAttribute) {
                    attributesKey = 'resource_attributes'
                }
                return logs
                    .filter((l) => props.attribute in l[attributesKey])
                    .map((l) => l[attributesKey][props.attribute])
            },
        ],
        breakdowns: [
            (s) => [s.attributeValues],
            (attributeValues: string[]) =>
                attributeValues.reduce(
                    (acc, value) => {
                        acc[value] = (acc[value] || 0) + 1
                        return acc
                    },
                    {} as {
                        [key: string]: number
                    }
                ),
        ],
    })),
])
