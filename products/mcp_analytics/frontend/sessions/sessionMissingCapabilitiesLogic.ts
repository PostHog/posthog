import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { hogql } from 'lib/utils/hogql'

import { NodeKind } from '~/queries/schema/schema-general'

export interface SessionMissingCapabilitiesProps {
    sessionId: string
    sessionStart: string
    sessionEnd: string
}

export interface MissingCapabilityReport {
    timestamp: string
    report: string
    /** Empty when none. */
    suggestion: string
}

export const sessionMissingCapabilitiesLogic = kea([
    path((key) => ['products', 'mcp_analytics', 'frontend', 'sessions', 'sessionMissingCapabilitiesLogic', key]),
    props({} as SessionMissingCapabilitiesProps),
    key((props) => props.sessionId),
    loaders(({ props }) => ({
        reports: [
            [] as MissingCapabilityReport[],
            {
                loadReports: async () => {
                    // JSONExtractString decodes escapes such as \n, which the plain property access keeps as text.
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT timestamp,
    JSONExtractString(properties, '$mcp_intent') AS report,
    JSONExtractString(properties, '$mcp_feedback_suggested_improvement') AS suggestion
FROM events
WHERE (event = '$mcp_missing_capability'
        OR (event = '$mcp_feedback' AND properties.$mcp_feedback_type = 'missing_capability'))
    AND coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id)) = ${props.sessionId}
    AND timestamp >= toDateTime(${props.sessionStart}) - INTERVAL 1 HOUR
    AND timestamp <= toDateTime(${props.sessionEnd}) + INTERVAL 1 HOUR
    AND notEmpty(report)
ORDER BY timestamp
LIMIT 50`,
                    })
                    return (response.results ?? []).map(([timestamp, report, suggestion]: any[]) => ({
                        timestamp: String(timestamp),
                        report: String(report),
                        suggestion: String(suggestion ?? ''),
                    }))
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadReports()
    }),
])
