import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

import { describeLogsQuery, extractLogRows } from './logsQueryToolOutput'

function toolMessage(rawOutput: unknown, innerInput?: Record<string, unknown>): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'query-logs',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('logsQueryToolOutput', () => {
    describe('extractLogRows', () => {
        it.each(['direct', 'structuredContent', 'app metadata'])(
            'maps rows from %s to severity, body, and timestamp',
            (source) => {
                const payload = {
                    results: [
                        { severity_text: 'error', body: 'connection refused', timestamp: '2026-09-08T10:00:00Z' },
                        { severity_text: 'info', body: 'request served', timestamp: '2026-09-08T10:00:01Z' },
                    ],
                }
                const content = [{ type: 'text', text: '2 log entries' }]
                const output =
                    source === 'direct'
                        ? payload
                        : source === 'structuredContent'
                          ? { content, structuredContent: payload }
                          : { content, _meta: { 'com.posthog.mcp/app_data': payload } }
                const rows = extractLogRows(toolMessage(output))

                expect(rows).toEqual([
                    { severityText: 'error', body: 'connection refused', timestamp: '2026-09-08T10:00:00Z' },
                    { severityText: 'info', body: 'request served', timestamp: '2026-09-08T10:00:01Z' },
                ])
            }
        )

        it('returns an empty array when the query matched no rows', () => {
            expect(extractLogRows(toolMessage({ results: [] }))).toEqual([])
        })

        it('returns null when the output has no results array', () => {
            expect(extractLogRows(toolMessage({ count: 3 }))).toBeNull()
            expect(extractLogRows(toolMessage({ results: 'nope' }))).toBeNull()
            expect(extractLogRows(toolMessage({ content: [{ type: 'text', text: '{"results": []}' }] }))).toBeNull()
        })

        it('defaults missing row fields to empty strings', () => {
            const rows = extractLogRows(toolMessage({ results: [{ severity_text: 'warn' }] }))
            expect(rows).toEqual([{ severityText: 'warn', body: '', timestamp: '' }])
        })
    })

    describe('describeLogsQuery', () => {
        it('summarizes services, severities, search, and date range from query args', () => {
            const subtitle = describeLogsQuery(
                toolMessage(
                    {},
                    {
                        query: {
                            serviceNames: ['api-gateway'],
                            severityLevels: ['error', 'fatal'],
                            searchTerm: 'timeout',
                            dateRange: { date_from: '-6h' },
                        },
                    }
                )
            )
            expect(subtitle).toBe('api-gateway · error, fatal · search: timeout · -6h')
        })

        it('reads args that are not nested under a query object', () => {
            expect(describeLogsQuery(toolMessage({}, { serviceNames: ['web'] }))).toBe('web')
        })

        it('returns undefined when there is nothing to describe', () => {
            expect(describeLogsQuery(toolMessage({}, { query: {} }))).toBeUndefined()
            expect(describeLogsQuery(toolMessage({}, undefined))).toBeUndefined()
        })
    })
})
