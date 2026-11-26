import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

export const changeFromPrevious = (value: number | undefined, previous: number | undefined): number | undefined =>
    value === undefined || previous === undefined || previous === 0 ? undefined : ((value - previous) / previous) * 100

const share = (part: number, whole: number): number | undefined => (whole > 0 ? (part / whole) * 100 : undefined)

export const rateItem = (
    key: string,
    current: { part: number; whole: number },
    previous: { part: number; whole: number } | null,
    caption?: string
): OverviewMetricCardItem => {
    const value = share(current.part, current.whole)
    const before = previous ? share(previous.part, previous.whole) : undefined
    return {
        key,
        kind: 'percentage',
        value,
        previous: before,
        changeFromPreviousPct: changeFromPrevious(value, before),
        caption,
    }
}

export const countItem = (key: string, value: number, caption?: string): OverviewMetricCardItem => ({
    key,
    kind: 'unit',
    value,
    caption,
})

const positionLabel = (position: number | null | undefined): string | undefined =>
    position === null || position === undefined ? undefined : `#${position.toFixed(1)}`

export const positionItem = (
    key: string,
    position: number | null,
    previous: number | null,
    caption?: string
): OverviewMetricCardItem => ({
    key,
    kind: 'unit',
    value: positionLabel(position) ?? 'Not cited',
    previous: positionLabel(previous),
    changeFromPreviousPct: changeFromPrevious(position ?? undefined, previous ?? undefined),
    isIncreaseBad: true,
    caption,
})

export const averageRateItem = (key: string, rate: number | null, caption?: string): OverviewMetricCardItem => ({
    key,
    kind: 'percentage',
    value: rate === null ? undefined : rate * 100,
    caption,
})
