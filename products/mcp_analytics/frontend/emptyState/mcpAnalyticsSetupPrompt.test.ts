import { mcpAnalyticsSetupPrompt } from './mcpAnalyticsSetupPrompt'

describe('mcpAnalyticsSetupPrompt', () => {
    it.each(['https://us.posthog.com', 'https://eu.posthog.com', 'https://analytics.example.com'])(
        'targets the selected project on %s',
        (origin) => {
            const prompt = mcpAnalyticsSetupPrompt(123, origin)
            expect(prompt).toContain(`project 123 at ${origin}`)
            expect(prompt).toContain(`${origin}/project/123/mcp-analytics/activity`)
            expect(prompt).not.toContain('/project/2/')
        }
    )
})
