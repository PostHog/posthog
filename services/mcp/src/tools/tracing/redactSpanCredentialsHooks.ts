import { isSpanCredentialName, redactCredentials, redactCredentialsInText } from '@/lib/credential-redaction'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// Span names, attributes, events and error messages are application text, so they can carry credentials.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    if (!isRecord(result) || !isRecord(result.summary) || !isRecord(result.summary.services)) {
        return redactCredentials(result, isSpanCredentialName)
    }
    // `summary.services` maps service names to span counts, so a service called `auth` must not mask its count.
    const { services, ...summary } = result.summary
    const redacted = redactCredentials({ ...result, summary }, isSpanCredentialName) as {
        summary: Record<string, unknown>
    }
    redacted.summary.services = Object.fromEntries(
        Object.entries(services).map(([name, count]) => [
            redactCredentialsInText(name, isSpanCredentialName),
            redactCredentials(count, isSpanCredentialName),
        ])
    )
    return redacted
}

export default { afterResponse } satisfies ToolHooks<unknown>
