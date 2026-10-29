import type { CaptureResult } from 'posthog-js'

import { WebMCPToolError, dropWebMCPToolErrors } from './webmcpToolError'

function exceptionEvent(properties: Record<string, unknown>): CaptureResult {
    return { uuid: 'uuid', event: '$exception', properties }
}

const toolCallException = {
    $exception_source: 'mcp.tool_call',
    $mcp_interface: 'webmcp',
}

describe('dropWebMCPToolErrors', () => {
    test.each([
        {
            name: 'a failed PostHog command',
            properties: {
                ...toolCallException,
                $exception_list: [{ type: new WebMCPToolError('Not found').name, value: 'Not found' }],
            },
            dropped: true,
        },
        {
            name: 'a transport failure in a tool call',
            properties: {
                ...toolCallException,
                $exception_list: [{ type: 'TypeError', value: 'Failed to read response body' }],
            },
            dropped: false,
        },
        {
            name: 'an app exception with the same error type',
            properties: { $exception_list: [{ type: new WebMCPToolError('Not found').name, value: 'Not found' }] },
            dropped: false,
        },
    ])('handles $name', ({ properties, dropped }) => {
        const event = exceptionEvent(properties)
        expect(dropWebMCPToolErrors(event)).toEqual(dropped ? null : event)
    })
})
