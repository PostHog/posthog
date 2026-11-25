/** An emptied number input reports NaN, which JSON would store as null. */
export function numberOrUnset(value: number | undefined): number | undefined {
    return value === undefined || Number.isNaN(value) ? undefined : value
}
