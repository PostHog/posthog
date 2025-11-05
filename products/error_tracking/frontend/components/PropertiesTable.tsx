import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export type PropertiesTableProps = {
    entries: [string, unknown][]
    alternatingColors?: boolean
}

export function PropertiesTable({ entries, alternatingColors = true }: PropertiesTableProps): JSX.Element {
    return (
        <LemonTable
            embedded
            size="small"
            dataSource={entries.filter(([, value]) => value !== undefined).map(([key, value]) => ({ key, value }))}
            showHeader={false}
            columns={[
                {
                    title: 'Key',
                    key: 'key',
                    dataIndex: 'key',
                    width: 0,
                    className: 'font-medium bg-inherit',
                    render: (dataValue, record) => (
                        <div className="flex gap-x-2 justify-between items-center">
                            <div>{dataValue}</div>
                            <LemonButton
                                size="xsmall"
                                tooltip="Copy value"
                                className="invisible group-hover:visible"
                                onClick={() =>
                                    copyToClipboard(copyValue(record.value)).catch((error) => {
                                        console.error('Failed to copy to clipboard:', error)
                                    })
                                }
                            >
                                <IconCopy />
                            </LemonButton>
                        </div>
                    ),
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                    className: 'whitespace-nowrap',
                    render: (value) => {
                        return <div className="whitespace-nowrap">{renderValue(value)}</div>
                    },
                },
            ]}
            rowClassName={
                alternatingColors ? 'even:bg-fill-tertiary odd:bg-surface-primary group' : 'bg-fill-secondary group'
            }
            firstColumnSticky
        />
    )
}

function copyValue(value: unknown): string {
    // oxlint-disable-next-line
    if (value && typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

function renderValue(value: unknown): React.ReactNode {
    if (Array.isArray(value)) {
        return '[' + value.map(renderValue).join(', ') + ']'
    } else if (value && typeof value === 'object') {
        return (
            '{' +
            Object.entries(value)
                .map(([k, v]) => `${k}: ${renderValue(v)}`)
                .join(', ') +
            '}'
        )
    } else if (typeof value === 'string') {
        if (value === '$$_posthog_redacted_based_on_masking_rules_$$') {
            return (
                <Tooltip title="Value redacted by SDK code variables masking configuration">
                    <span className="text-muted">***</span>
                </Tooltip>
            )
        }
        if (/^https?:\/\/.+/.test(value)) {
            return (
                <Link to={value as string} target="_blank">
                    {value}
                </Link>
            )
        }
        return value // no quotes
    }
    return String(value)
}
