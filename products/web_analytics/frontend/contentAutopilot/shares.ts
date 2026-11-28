import type { KpiDelta } from './promptReport'

// Floating-point products such as 0.145 * 100 = 14.499999999999998 would round down. Cutting the product to
// 12 significant digits first rounds them the way the number reads.
const roundTo = (value: number, decimals: number): number => {
    const factor = 10 ** decimals
    return Math.round(Number((value * factor).toPrecision(12))) / factor
}

// Under 10% a whole percent rounds a small share to 0%, so it keeps one decimal. The test runs on the value
// rounded to one decimal, so 9.96% reads 10% and not 10.0%.
const shareDecimals = (share: number): number => (Math.abs(roundTo(share * 100, 1)) < 10 ? 1 : 0)

/** A share of answers (0-1) in percent, rounded once, the way `formatShare` shows it. */
export const displayedPercent = (share: number): number => roundTo(share * 100, shareDecimals(share))

/** A share of answers (0-1): one decimal under 10%, so 0.005 reads 0.5% and not 0%, and whole percents above.
 *  The decimal stays when it is a zero, so 8.0% sits in a column of 7.4% and 9.1%. The label is printed from
 *  `displayedPercent`, so a change taken from it always matches the labels. */
export const formatShare = (share: number): string =>
    share === 0 ? '0%' : `${displayedPercent(share).toFixed(shareDecimals(share))}%`

/** The change between two shares in percentage points, taken from the values as `formatShare` shows them,
 *  so a row never reads 1% then 0% with +1.1 pts. Null when either side is missing. */
export const shareChange = (share: number | null, previous: number | null): number | null =>
    share === null || previous === null ? null : roundTo(displayedPercent(share) - displayedPercent(previous), 1)

/** A change in percentage points as a delta label, from two shares as they are shown. */
export const shareDelta = (share: number, previous: number, tooltip: string): KpiDelta => {
    const points = shareChange(share, previous) ?? 0
    return {
        label: points === 0 ? 'No change' : `${points > 0 ? '+' : ''}${points} pts`,
        direction: points === 0 ? 'flat' : points > 0 ? 'up' : 'down',
        tooltip,
    }
}
