import type { ReactElement } from 'react'

import { Badge, Tooltip } from '@posthog/mosaic'

export interface PropertyFilter {
    key: string
    value: unknown
    operator?: string
    type?: string
}

export interface PropertyFilterListProps {
    filters: PropertyFilter[]
}

function formatValue(value: unknown): string {
    if (Array.isArray(value)) {
        return value.join(', ')
    }
    return String(value ?? '')
}

interface OperatorDisplay {
    short: string
    full: string
}

const operatorDisplays: Record<string, OperatorDisplay> = {
    exact: { short: '=', full: 'exact match' },
    is_not: { short: '\u2260', full: 'does not equal' },
    icontains: { short: 'contains', full: 'contains (case insensitive)' },
    not_icontains: { short: 'not contains', full: 'does not contain' },
    regex: { short: '~', full: 'matches regex' },
    not_regex: { short: '!~', full: 'does not match regex' },
    gt: { short: '>', full: 'greater than' },
    gte: { short: '\u2265', full: 'greater than or equal' },
    lt: { short: '<', full: 'less than' },
    lte: { short: '\u2264', full: 'less than or equal' },
    is_set: { short: 'is set', full: 'property exists' },
    is_not_set: { short: 'is not set', full: 'property does not exist' },
}

function getOperatorDisplay(operator?: string): OperatorDisplay {
    return operatorDisplays[operator ?? 'exact'] ?? { short: operator ?? '=', full: operator ?? 'equals' }
}

export function PropertyFilterList({ filters }: PropertyFilterListProps): ReactElement {
    if (filters.length === 0) {
        return <span className="text-sm text-text-secondary">No property filters</span>
    }

    return (
        <div className="flex flex-col gap-1.5">
            {filters.map((filter, i) => {
                const op = getOperatorDisplay(filter.operator)
                return (
                    <div key={i} className="flex items-center gap-1.5 text-sm flex-wrap">
                        <Badge variant="info" size="sm">
                            {filter.key}
                        </Badge>
                        <Tooltip content={op.full} position="top">
                            <span className="text-text-secondary cursor-default">{op.short}</span>
                        </Tooltip>
                        {filter.operator !== 'is_set' && filter.operator !== 'is_not_set' && (
                            <span className="font-medium text-text-primary">{formatValue(filter.value)}</span>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
