/** No decimals at 10% and above. Heads such as `action` have low base rates, so one decimal below 10%. */
export function formatRankingProbability(probability: number): string {
    const percent = probability * 100
    const oneDecimal = Math.round(percent * 10) / 10
    return oneDecimal >= 10 ? `${Math.round(percent)}%` : `${oneDecimal.toFixed(1)}%`
}

/** One decimal below 10x, no decimals at 10x and above. */
export function formatRankingLift(lift: number): string {
    const oneDecimal = Math.round(lift * 10) / 10
    return oneDecimal >= 10 ? `${Math.round(lift)}x` : `${oneDecimal.toFixed(1)}x`
}

/**
 * Bar width in percent for a lift on a log scale. 1x sits at 50%, and the bar clamps at 0.1x and 10x,
 * so a lift and its inverse sit at equal distances from the center.
 */
export function rankingLiftBarPercent(lift: number): number {
    if (!(lift > 0)) {
        return 0
    }
    const position = (Math.log10(lift) + 1) / 2
    return Math.min(1, Math.max(0, position)) * 100
}
