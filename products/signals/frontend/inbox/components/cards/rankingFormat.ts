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

/** The card pill text. The split uses the rounded lift, so a pill never reads "1.0x more likely". */
export function formatRankingLiftComparison(lift: number): string {
    const formatted = formatRankingLift(lift)
    return parseFloat(formatted) > 1 ? `${formatted} more likely` : `${formatted} as likely`
}

/**
 * Bar position in percent for a lift on a log scale. 1x sits at 50%, and the bar clamps at 0.1x and 10x,
 * so a lift and its inverse sit at equal distances from the center.
 */
export function rankingLiftBarPercent(lift: number): number {
    if (!(lift > 0)) {
        return 0
    }
    const position = (Math.log10(lift) + 1) / 2
    return Math.min(1, Math.max(0, position)) * 100
}

/** The bar fill in percent. It starts at 1x in the center and grows right above 1x and left below 1x. */
export function rankingLiftBarFill(lift: number): { left: number; width: number } {
    const percent = rankingLiftBarPercent(lift)
    return { left: Math.min(50, percent), width: Math.abs(percent - 50) }
}

export type RankingStrength = 'very_likely' | 'likely' | 'average' | 'unlikely'

export const RANKING_STRENGTH_LABELS: Record<RankingStrength, string> = {
    very_likely: 'Very likely',
    likely: 'Likely',
    average: 'About average',
    unlikely: 'Unlikely',
}

/** A lift as a word. The bands sit at equal distances from 1x on the bar's log scale. */
export function rankingStrength(lift: number): RankingStrength {
    if (lift >= 2) {
        return 'very_likely'
    }
    if (lift >= 1.25) {
        return 'likely'
    }
    if (lift > 0.8) {
        return 'average'
    }
    return 'unlikely'
}
