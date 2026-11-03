import { dimHexColor } from './compareDimming'

const FADED_SERIES_OPACITY = 0.25

export function withHighlightedSeries<T>(
    getColor: (result: T) => string,
    results: T[],
    isHighlighted: ((result: T) => boolean) | undefined
): (result: T) => string {
    if (!isHighlighted || !results.some(isHighlighted)) {
        return getColor
    }
    return (result) => (isHighlighted(result) ? getColor(result) : dimHexColor(getColor(result), FADED_SERIES_OPACITY))
}
