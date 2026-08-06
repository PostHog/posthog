import { IconCopy, IconFilter, IconInfo } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { Button, Table, TableBody, TableCell, TableRow, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

type PropertyTableRow = {
    key: string
    value: unknown
    filterKey?: string
    filterValue?: unknown
}

export type PropertiesTableProps = {
    entries: ([string, unknown] | PropertyTableRow)[]
    alternatingColors?: boolean
    onFilterValue?: (key: string, value: string | number | boolean) => void
}

export function PropertiesTable({
    entries,
    alternatingColors = true,
    onFilterValue,
}: PropertiesTableProps): JSX.Element {
    const rows: PropertyTableRow[] = entries
        .map((entry) => {
            if (Array.isArray(entry)) {
                return { key: entry[0], value: entry[1], filterKey: entry[0], filterValue: entry[1] }
            }
            return entry
        })
        .filter((entry) => entry.value !== undefined)

    return (
        <Table fullWidth size="sm">
            <TableBody>
                {rows.map((record, index) => {
                    const filterableValue = getFilterableValue(record.filterValue ?? record.value)

                    return (
                        <TableRow
                            key={`${record.key}-${index}`}
                            className={
                                alternatingColors
                                    ? 'group odd:bg-[var(--card)] even:bg-[var(--muted)]'
                                    : 'group bg-[var(--card)]'
                            }
                        >
                            <TableCell className="sticky left-0 z-10 bg-inherit font-medium">
                                <div className="flex items-center justify-between gap-x-2">
                                    <div>{record.key}</div>
                                    <div className="flex items-center gap-1">
                                        {onFilterValue && record.filterKey && filterableValue !== null && (
                                            <Tooltip>
                                                <TooltipTrigger
                                                    render={
                                                        <Button
                                                            variant="default"
                                                            size="icon-xs"
                                                            className="invisible group-hover:visible"
                                                            onClick={() =>
                                                                onFilterValue(record.filterKey!, filterableValue)
                                                            }
                                                            aria-label="Filter by this value"
                                                        />
                                                    }
                                                >
                                                    <IconFilter />
                                                </TooltipTrigger>
                                                <TooltipContent>Filter by this value</TooltipContent>
                                            </Tooltip>
                                        )}
                                        <Tooltip>
                                            <TooltipTrigger
                                                render={
                                                    <Button
                                                        variant="default"
                                                        size="icon-xs"
                                                        className="invisible group-hover:visible"
                                                        onClick={() =>
                                                            copyToClipboard(copyValue(record.value)).catch((error) => {
                                                                console.error('Failed to copy to clipboard:', error)
                                                            })
                                                        }
                                                        aria-label="Copy value"
                                                    />
                                                }
                                            >
                                                <IconCopy />
                                            </TooltipTrigger>
                                            <TooltipContent>Copy value</TooltipContent>
                                        </Tooltip>
                                    </div>
                                </div>
                            </TableCell>
                            <TableCell className="whitespace-nowrap">{renderValue(record.value)}</TableCell>
                        </TableRow>
                    )
                })}
            </TableBody>
        </Table>
    )
}

const SENTINELS = {
    Redacted: '$$_posthog_redacted_based_on_masking_rules_$$',
    ValueTooLong: '$$_posthog_value_too_long_$$',
}

const SENTINEL_REPLACEMENTS: Record<string, string> = {
    [SENTINELS.Redacted]: '***',
    [SENTINELS.ValueTooLong]: '<value too long>',
}

function normalizeSentinels(str: string): string {
    let result = str
    for (const [sentinel, replacement] of Object.entries(SENTINEL_REPLACEMENTS)) {
        result = result.replaceAll(sentinel, replacement)
    }
    return result
}

function copyValue(value: unknown): string {
    // oxlint-disable-next-line
    if (value && typeof value === 'object') {
        return normalizeSentinels(JSON.stringify(value))
    }
    return normalizeSentinels(String(value))
}

function getFilterableValue(value: unknown): string | number | boolean | null {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return value
    }
    return null
}

function renderValue(value: unknown, level = 0): React.ReactNode {
    if (Array.isArray(value)) {
        return '[' + value.map((v) => renderValue(v, level + 1)).join(', ') + ']'
    } else if (value && typeof value === 'object') {
        return (
            '{' +
            Object.entries(value)
                .map(([k, v]) => `${k}: ${renderValue(v, level + 1)}`)
                .join(', ') +
            '}'
        )
    } else if (typeof value === 'string') {
        if (value === SENTINELS.Redacted) {
            return (
                <MaskedValue
                    value="***"
                    tooltip="This value got redacted by SDK code variables masking configuration"
                />
            )
        }
        if (value.includes(SENTINELS.Redacted)) {
            return (
                <MaskedValue
                    value={normalizeSentinels(value)}
                    tooltip="Some values inside got redacted by SDK code variables masking configuration"
                />
            )
        }
        if (value === SENTINELS.ValueTooLong) {
            return (
                <MaskedValue
                    value="<value too long>"
                    tooltip="This value was truncated because it exceeded the maximum allowed length"
                />
            )
        }
        if (value.includes(SENTINELS.ValueTooLong)) {
            return (
                <MaskedValue
                    value={normalizeSentinels(value)}
                    tooltip="Some values inside were truncated because they exceeded the maximum allowed length"
                />
            )
        }
        if (/^https?:\/\/.+/.test(value)) {
            if (level > 0) {
                return value
            }
            return (
                <span className="contents">
                    <Link to={value} target="_blank">
                        {value}
                    </Link>
                </span>
            )
        }
        return value // no quotes
    }
    return String(value)
}

export function MaskedValue({ value, tooltip }: { value: string; tooltip: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1">
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" tabIndex={0} aria-label={tooltip} />}>
                    <IconInfo className="text-sm text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
            {value}
        </span>
    )
}
