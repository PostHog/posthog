import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { OverviewResponseFormat } from './types/schemas'

export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs))
}

// Number formatting utilities
export function formatNumber(value: number, format: OverviewResponseFormat = 'number', compact = true): string {
    switch (format) {
        case 'percentage':
            return `${value.toFixed(1)}%`

        case 'currency':
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD',
                notation: compact ? 'compact' : 'standard',
                maximumFractionDigits: 1,
            }).format(value)

        case 'duration_seconds':
            if (value < 60) {
                return `${Math.round(value)}s`
            }
            if (value < 3600) {
                return `${Math.round(value / 60)}m`
            }
            return `${Math.round(value / 3600)}h`

        case 'number':
        default:
            if (!compact) {
                return new Intl.NumberFormat('en-US').format(value)
            }

            if (value >= 1000000000) {
                return `${(value / 1000000000).toFixed(1)}B`
            }
            if (value >= 1000000) {
                return `${(value / 1000000).toFixed(1)}M`
            }
            if (value >= 1000) {
                return `${(value / 1000).toFixed(1)}K`
            }
            return value.toString()
    }
}

export function formatChangePercentage(change: number): string {
    const absChange = Math.abs(change)
    const sign = change >= 0 ? '+' : '-'
    return `${sign}${absChange.toFixed(1)}%`
}

export function getTooltipContent(
    value: number,
    previousValue: number | undefined | null,
    changePercentage: number | undefined | null,
    format: OverviewResponseFormat
): string {
    const currentFormatted = formatNumber(value, format, false)
    if (previousValue == null) {
        return currentFormatted
    }
    const previousFormatted = formatNumber(previousValue, format, false)
    if (previousValue === value || changePercentage === 0) {
        return `${currentFormatted}, same as previous period`
    }
    const isIncrease = value > previousValue
    const changeDirection = isIncrease ? 'increase' : 'decrease'
    if (!changePercentage) {
        return `${currentFormatted}, ${changeDirection} from ${previousFormatted}`
    }
    const changeFormatted = formatChangePercentage(changePercentage)
    return `${currentFormatted}, an ${changeDirection} of ${changeFormatted} from ${previousFormatted}`
}

// Theme utilities
