import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'
import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import { identifierToHuman } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { match } from 'ts-pattern'

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
            dataSource={entries
                .filter(([, value]) => value !== undefined)
                .map(([key, value]) => ({
                    key,
                    value: String(value),
                }))}
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
                                    copyToClipboard(record.value).catch((error) => {
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
                },
            ]}
            rowClassName="even:bg-fill-tertiary odd:bg-surface-primary group"
            firstColumnSticky
        />
    )
}
