// HogQL results arrive untyped; ClickHouse returns booleans as 0/1 and numbers
// possibly stringified. Coerce numerically so a stringified "0" can never read
// as truthy.
export const asNumber = (value: unknown): number => Number(value) || 0

export const asOptionalString = (value: unknown): string | null =>
    typeof value === 'string' && value !== '' ? value : null
