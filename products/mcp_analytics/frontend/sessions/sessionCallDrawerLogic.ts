import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import type { MCPDetailDrawerPosition } from '../components/MCPDetailDrawer'
import { fetchToolCallEvent } from '../earlyData/activityDrawerLogic'
import { MCPToolCallApi } from '../generated/api.schemas'

export const sessionCallDrawerLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'sessions', 'sessionCallDrawerLogic']),
    actions({
        openCall: (call: MCPToolCallApi, calls: MCPToolCallApi[]) => ({ call, calls }),
        stepTo: (direction: 'previous' | 'next') => ({ direction }),
        close: true,
    }),
    reducers({
        calls: [[] as MCPToolCallApi[], { openCall: (_, { calls }) => calls }],
        openedCall: [
            null as MCPToolCallApi | null,
            {
                openCall: (_, { call }) => call,
                close: () => null,
            },
        ],
    }),
    loaders(() => ({
        event: [
            null as EventType | null,
            {
                loadEvent: async (call: MCPToolCallApi, breakpoint) => {
                    const event = await fetchToolCallEvent(call.event_id, call.timestamp)
                    breakpoint()
                    return event
                },
            },
        ],
    })),
    reducers({
        eventFailed: [
            false,
            {
                loadEvent: () => false,
                loadEventFailure: () => true,
            },
        ],
    }),
    selectors({
        position: [
            (s) => [s.calls, s.openedCall],
            (calls: MCPToolCallApi[], openedCall: MCPToolCallApi | null): MCPDetailDrawerPosition | null => {
                const index = openedCall ? calls.findIndex((call) => call.event_id === openedCall.event_id) : -1
                return index >= 0 ? { index, total: calls.length } : null
            },
        ],
        previousCall: [
            (s) => [s.calls, s.position],
            (calls: MCPToolCallApi[], position: MCPDetailDrawerPosition | null): MCPToolCallApi | null =>
                position && position.index > 0 ? calls[position.index - 1] : null,
        ],
        nextCall: [
            (s) => [s.calls, s.position],
            (calls: MCPToolCallApi[], position: MCPDetailDrawerPosition | null): MCPToolCallApi | null =>
                position && position.index < calls.length - 1 ? calls[position.index + 1] : null,
        ],
        fullPageHref: [
            (s) => [s.openedCall],
            (openedCall: MCPToolCallApi | null): string | null =>
                openedCall ? urls.event(openedCall.event_id, openedCall.timestamp, MCP_TOOL_CALL_EVENT) : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        openCall: ({ call }) => {
            posthog.capture('mcp analytics drawer opened', { list: 'session' })
            actions.loadEvent(call)
        },
        stepTo: ({ direction }) => {
            const call = direction === 'previous' ? values.previousCall : values.nextCall
            if (call) {
                actions.openCall(call, values.calls)
            }
        },
    })),
])
