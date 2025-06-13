import { IconCopy } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import useIsHovering from 'lib/hooks/useIsHovering'
import { identifierToHuman, isObject } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { match } from 'ts-pattern'

import { cancelEvent } from '../utils'

export interface ContextDisplayProps {
    className?: string
    attributes?: ExceptionAttributes
    additionalProperties?: Record<string, unknown>
    loading: boolean
}

export function ContextDisplay({
    className,
    attributes,
    additionalProperties = {},
    loading,
}: ContextDisplayProps): JSX.Element {
    return (
        <div className={className}>
            {match(loading)
                .with(true, () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with(false, () => {
                    const additionalEntries = Object.entries(additionalProperties).map(
                        ([key, value]) => [identifierToHuman(key, 'title'), value] as [string, unknown]
                    )
                    const exceptionEntries =
                        attributes &&
                        ([
                            ['Level', attributes.level],
                            ['Synthetic', attributes.synthetic],
                            ['Library', concatValues(attributes, 'lib', 'libVersion')],
                            ['Handled', attributes.handled],
                            ['Browser', concatValues(attributes, 'browser', 'browserVersion')],
                            ['OS', concatValues(attributes, 'os', 'osVersion')],
                            ['URL', attributes.url],
                        ] as [string, unknown][])
                    return (
                        <div className="space-y-2">
                            <ContextTable entries={exceptionEntries || []} />
                            {additionalEntries.length > 0 && <ContextTable entries={additionalEntries} />}
                        </div>
                    )
                })
                .exhaustive()}
        </div>
    )
}

type ContextRowProps = {
    label: string
    value: string
}

function ContextTable({ entries }: { entries: [string, unknown][] }): JSX.Element {
    return (
        <table
            className="border-spacing-0 border-separate rounded w-full border overflow-hidden cursor-default"
            onClick={cancelEvent}
        >
            <tbody className="w-full">
                {entries
                    .filter(([, value]) => value !== undefined)
                    .map(([key, value]) => (
                        <ContextRow
                            key={key}
                            label={key}
                            value={isObject(value) ? JSON.stringify(value) : String(value)}
                        />
                    ))}
                {entries.length == 0 && <tr className="w-full text-center">No data available</tr>}
            </tbody>
        </table>
    )
}

function ContextRow({ label, value }: ContextRowProps): JSX.Element {
    const valueRef = useRef<HTMLTableCellElement>(null)
    const isHovering = useIsHovering(valueRef)

    return (
        <tr className="even:bg-fill-tertiary w-full group">
            <th className="border-r-1 font-semibold text-xs p-1 w-1/3 text-left">{label}</th>
            <td ref={valueRef} className="w-full truncate p-1 text-xs max-w-0 relative" title={value}>
                {value}
                <div
                    className={cn(
                        'absolute right-0 top-[50%] translate-y-[-50%] group-even:bg-fill-tertiary group-odd:bg-fill-primary drop-shadow-sm',
                        isHovering ? 'opacity-100' : 'opacity-0'
                    )}
                >
                    <LemonButton
                        size="xsmall"
                        className={cn('p-0 rounded-none')}
                        tooltip="Copy"
                        onClick={() => {
                            copyToClipboard(value).catch((error) => {
                                console.error('Failed to copy to clipboard:', error)
                            })
                        }}
                    >
                        <IconCopy />
                    </LemonButton>
                </div>
            </td>
        </tr>
    )
}
