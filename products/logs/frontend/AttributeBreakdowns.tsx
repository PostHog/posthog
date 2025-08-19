import { useValues } from 'kea'

import { IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { PropertyOperator } from '~/types'

import { attributeBreakdownLogic } from './attributeBreakdownLogic'

export const AttributeBreakdowns = ({
    attribute,
    addFilter,
}: {
    attribute: string
    addFilter: (key: string, value: string, operator?: PropertyOperator) => void
}): JSX.Element => {
    const logic = attributeBreakdownLogic({ attribute })
    const { attributeValues, logCount, breakdowns } = useValues(logic)

    const dataSource = Object.entries(breakdowns)
        .sort(([, c1], [, c2]) => c2 - c1)
        .slice(0, 10)
        .map(([value, count]) => ({
            value,
            count,
            percentage: ((count / attributeValues.length) * 100).toFixed(0),
        }))

    return (
        <div className="flex flex-col p-2 gap-y-2">
            {attributeValues.length} of the {logCount} logs have the label {attribute}
            <LemonTable
                hideScrollbar
                dataSource={dataSource}
                size="small"
                columns={[
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, record) => (
                            <div className="flex gap-x-0">
                                <LemonButton
                                    tooltip="Add as filter"
                                    size="xsmall"
                                    onClick={() => addFilter(attribute, record.value)}
                                >
                                    <IconPlusSquare />
                                </LemonButton>
                                <LemonButton
                                    tooltip="Exclude as filter"
                                    size="xsmall"
                                    onClick={() => addFilter(attribute, record.value, PropertyOperator.IsNot)}
                                >
                                    <IconMinusSquare />
                                </LemonButton>
                            </div>
                        ),
                    },
                    {
                        title: 'Count',
                        key: 'count',
                        dataIndex: 'count',
                        width: 0,
                    },
                    {
                        title: 'Percentage',
                        key: 'percentage',
                        dataIndex: 'percentage',
                        width: 0,
                        render: (value) => `${value}%`,
                    },
                    {
                        title: 'Value',
                        key: 'value',
                        dataIndex: 'value',
                    },
                ]}
            />
        </div>
    )
}
