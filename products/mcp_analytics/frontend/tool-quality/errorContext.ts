import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

export interface MCPErrorContext {
    toolName: string
    errorType: string
    errorStatus?: string
    errorMessage?: string
    timestamp?: string
    harness?: string
    intent?: string
    sessionId?: string
}

export function mcpSessionUrl(sessionId: string): string {
    return `${urls.mcpAnalyticsSessions()}?search=${encodeURIComponent(sessionId)}`
}

function absoluteUrl(path: string): string {
    return `${window.location.origin}${addProjectIdIfMissing(path)}`
}

/**
 * Paste-ready markdown block describing one MCP tool failure, aimed at handing to a coding
 * agent ("please fix") or seeding a task description. Shared by the occurrences drill-down's
 * copy button and the create-task flow so both surfaces carry identical context.
 */
export function formatErrorContext(ctx: MCPErrorContext): string {
    const bucket = ctx.errorStatus ? `${ctx.errorType} (HTTP ${ctx.errorStatus})` : ctx.errorType
    const lines = [`## MCP tool failure: ${ctx.toolName}`, '', `- Error type: ${bucket}`]
    if (ctx.timestamp) {
        lines.push(`- When: ${ctx.timestamp}`)
    }
    if (ctx.harness) {
        lines.push(`- Harness: ${ctx.harness}`)
    }
    if (ctx.sessionId) {
        lines.push(`- Session: ${ctx.sessionId}`)
    }
    if (ctx.intent && ctx.intent !== '{}') {
        lines.push(`- Agent intent: ${ctx.intent}`)
    }
    lines.push('')
    if (ctx.errorMessage) {
        lines.push('Error message:', '```', ctx.errorMessage, '```')
    } else {
        lines.push('Error message: not captured (event predates error message capture).')
    }
    lines.push('', `Tool report: ${absoluteUrl(urls.mcpAnalyticsTool(ctx.toolName))}`)
    if (ctx.sessionId) {
        lines.push(`Session log: ${absoluteUrl(mcpSessionUrl(ctx.sessionId))}`)
    }
    return lines.join('\n')
}
