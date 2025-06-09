import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { attributeBreakdownLogic } from './attributeBreakdownLogic'

export const AttributeBreakdowns = ({ attribute }: { attribute: string }): JSX.Element => {
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
