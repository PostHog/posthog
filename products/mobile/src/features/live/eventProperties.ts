export function customEventProperties(properties: Record<string, unknown>): [string, string][] {
    return Object.entries(properties)
        .filter(([key]) => !key.startsWith('$') && key !== 'distinct_id' && key !== 'token')
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, value]) => [
            key,
            typeof value === 'string' ? value || '""' : (JSON.stringify(value, null, 2) ?? 'null'),
        ])
}
