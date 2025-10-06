import { match } from 'ts-pattern'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonTable, Link, Spinner } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import { identifierToHuman } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export type ContextDisplayProps = {
    loading: boolean
    exceptionAttributes: ExceptionAttributes | null
    additionalProperties: Record<string, unknown>
}

export function ContextDisplay({
    loading,
    exceptionAttributes,
    additionalProperties,
}: ContextDisplayProps): JSX.Element {
    const additionalEntries = Object.entries(additionalProperties).map(
        ([key, value]) => [identifierToHuman(key, 'title'), value] as [string, unknown]
    )
    const exceptionEntries: [string, unknown][] = exceptionAttributes
        ? [
              ['Level', exceptionAttributes.level],
              ['Synthetic', exceptionAttributes.synthetic],
              ['Library', concatValues(exceptionAttributes, 'lib', 'libVersion')],
              ['Handled', exceptionAttributes.handled],
              ['Browser', concatValues(exceptionAttributes, 'browser', 'browserVersion')],
              ['OS', concatValues(exceptionAttributes, 'os', 'osVersion')],
              ['URL', exceptionAttributes.url],
          ]
        : []

    return (
        <>
            {match(loading)
                .with(true, () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with(false, () => <ContextTable entries={[...exceptionEntries, ...additionalEntries]} />)
                .exhaustive()}
        </>
    )
}

type ContextTableProps = { entries: [string, unknown][] }

function ContextTable({ entries }: ContextTableProps): JSX.Element {
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
            rowClassName="even:bg-fill-tertiary odd:bg-surface-primary group"
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
