// Matches a single-quoted SQL string literal, honoring both escape styles
// ClickHouse/HogQL accept: backslash escapes (\') and doubled quotes ('').
const SQL_STRING_LITERAL = /'(?:[^'\\]|\\.|'')*'/g

// ISO dates/datetimes are kept: negligible PII on their own, and losing the
// query's time range would blind intent-vs-query judging for no privacy gain.
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z?)?$/

const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g

/**
 * Masks the contents of SQL string literals while preserving structure the
 * anti-pattern checks depend on: leading/trailing `%`/`_` wildcards survive,
 * so `'%john@acme.com%'` becomes `'%***%'`. Identifiers and numeric literals
 * are untouched.
 */
export function maskSqlLiterals(sql: string): string {
    return sql.replace(SQL_STRING_LITERAL, (literal) => {
        const inner = literal.slice(1, -1)
        if (inner === '' || ISO_DATE_TIME.test(inner)) {
            return literal
        }
        const leading = inner.match(/^[%_]+/)?.[0] ?? ''
        const trailing = inner.match(/[%_]+$/)?.[0] ?? ''
        if (leading.length + trailing.length >= inner.length) {
            return literal
        }
        return `'${leading}***${trailing}'`
    })
}

/** Masks email addresses in free text (agent-stated intents are user-authored). */
export function maskEmails(text: string): string {
    return text.replace(EMAIL, '<email>')
}
