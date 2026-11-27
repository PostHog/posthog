import { percentage } from 'lib/utils/numbers'

import type { KpiDelta } from './promptReport'

// Under this share a whole percent rounds a small share to 0%, so it keeps one decimal.
const DECIMAL_BELOW = 0.1

const shareDecimals = (share: number): number => (Math.abs(share) < DECIMAL_BELOW ? 1 : 0)

/** A share of answers (0-1) in percent, rounded the way `formatShare` shows it. */
export const displayedPercent = (share: number): number => {
    const factor = 10 ** shareDecimals(share)
    return Math.round(share * 100 * factor) / factor
}

/** A share of answers (0-1): one decimal under 10%, so 0.005 reads 0.5% and not 0%, and whole percents above. */
export const formatShare = (share: number): string => percentage(share, shareDecimals(share))

/** The change between two shares in percentage points, taken from the values as `formatShare` shows them,
 *  so a row never reads 1% then 0% with +1.1 pts. Null when either side is missing. */
export const shareChange = (share: number | null, previous: number | null): number | null =>
    share === null || previous === null
        ? null
        : Math.round((displayedPercent(share) - displayedPercent(previous)) * 10) / 10

/** A change in percentage points as a delta label, from two shares as they are shown. */
export const shareDelta = (share: number, previous: number, tooltip: string): KpiDelta => {
    const points = shareChange(share, previous) ?? 0
    return {
        label: points === 0 ? 'No change' : `${points > 0 ? '+' : ''}${points} pts`,
        direction: points === 0 ? 'flat' : points > 0 ? 'up' : 'down',
        tooltip,
    }
}
