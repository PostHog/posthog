// kea-router parses `?search=123` into a number and `?search=true` into a boolean, so a
// string-only check would drop text a person can type. Read a scalar back as the text it came
// from, and reject the array and object forms, which no inbox filter param ever takes.
export function readTextParam(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    return ''
}
