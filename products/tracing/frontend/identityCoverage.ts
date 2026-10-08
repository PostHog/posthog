import { percentage } from 'lib/utils/numbers'

/**
 * The share of `total` spans that carry the ID. A partly covered set never reads as a flat
 * 0% or 100%, because either would say the count beside it covers nothing or everything.
 */
export function formatIdentityCoverage(covered: number | undefined, total: number): string {
    if (!covered || !total) {
        return '0%'
    }
    const fraction = covered / total
    if (fraction < 0.005) {
        return '<1%'
    }
    if (fraction >= 0.995 && fraction < 1) {
        return '>99%'
    }
    return percentage(fraction, 0)
}
