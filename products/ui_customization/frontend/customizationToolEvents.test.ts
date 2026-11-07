import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import { customizationWasChanged } from './customizationToolEvents'

describe('customization tool completion', () => {
    it.each([
        ['ui-customization-set', 'completed', 'analytics_sidebar', true],
        ['ui-customization-reset', 'completed', 'analytics_sidebar', true],
        ['ui-customization-get', 'completed', 'analytics_sidebar', false],
        ['ui-customization-set', 'started', 'analytics_sidebar', false],
        ['ui-customization-set', 'failed', 'analytics_sidebar', false],
        ['ui-customization-set', 'completed', 'other_sidebar', false],
        ['ui-customization-set', 'completed', undefined, false],
    ] as const)('%s %s for %s reloads: %s', (toolName, phase, context, expected) => {
        const invocation: ToolStreamEvent['invocation'] = {
            toolCallId: 'customization-call',
            rawServerName: 'posthog',
            rawToolName: toolName,
            input: { context },
            status: 'completed',
            contentBlocks: [],
        }
        const event: ToolStreamEvent = {
            streamKey: 'customization-stream',
            toolCallId: invocation.toolCallId,
            toolName,
            rawToolName: toolName,
            phase,
            invocation,
            source: 'live',
        }
        expect(customizationWasChanged(event, 'analytics_sidebar')).toBe(expected)
        expect(
            customizationWasChanged(
                {
                    ...event,
                    rawToolName: 'exec',
                    invocation: {
                        ...invocation,
                        rawToolName: 'exec',
                        input: { command: `call ${toolName} ${JSON.stringify({ context })}` },
                    },
                },
                'analytics_sidebar'
            )
        ).toBe(expected)
    })
})
