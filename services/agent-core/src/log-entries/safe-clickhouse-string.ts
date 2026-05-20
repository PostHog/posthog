/**
 * Vendored from nodejs/src/utils/db/utils.ts.
 *
 * ClickHouse's JSON parser rejects lone Unicode surrogates. The CDP pipeline
 * escapes them before producing onto Kafka so the consumer doesn't have to.
 * We do the same.
 */
export function safeClickhouseString(str: string): string {
    return str.replace(/[\ud800-\udfff]/gu, (match) => {
        const res = JSON.stringify(match)
        return res.slice(1, res.length - 1) + `\\`
    })
}
