const COUNTER_NAME_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/

export function isValidCounterName(value: string): boolean {
    return COUNTER_NAME_PATTERN.test(value)
}
