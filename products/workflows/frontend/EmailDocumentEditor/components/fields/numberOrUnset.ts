/** An emptied number input reports NaN, which must not reach the document: it saves as null. */
export function numberOrUnset(value: number | undefined): number | undefined {
    return value === undefined || Number.isNaN(value) ? undefined : value
}
