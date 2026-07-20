import { getMCPNotificationUseCase } from './mcpAnalyticsNotificationsLogic'

describe('getMCPNotificationUseCase', () => {
    test.each([
        ['$mcp_missing_capability', 'missing-capability'],
        ['$mcp_tool_call', 'tool-error'],
        ['$pageview', null],
    ])('classifies the %s event as %s', (eventId, expected) => {
        expect(
            getMCPNotificationUseCase({
                filters: { events: [{ id: eventId, type: 'events' }] },
            })
        ).toBe(expected)
    })
})
