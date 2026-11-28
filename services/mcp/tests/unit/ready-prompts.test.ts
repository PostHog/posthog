import { describe, expect, it } from 'vitest'

import { getPromptsFromManifest } from '@/resources'

describe('ready-made prompts', () => {
    it('serves the web analytics prompts as one user message each', async () => {
        const prompts = await getPromptsFromManifest()

        expect(prompts.map((prompt) => prompt.name)).toMatchInlineSnapshot(`
          [
            "web-analytics-weekly-summary",
            "web-analytics-traffic-change",
            "web-analytics-compare-periods",
            "web-analytics-yesterday-vs-last-week",
            "web-analytics-top-pages",
            "web-analytics-traffic-sources",
            "web-analytics-worst-bounce-landing-pages",
            "web-analytics-goal-conversion-rate",
            "web-analytics-goal-conversion-by-channel",
            "web-analytics-set-up-conversion-goal",
            "web-analytics-worst-web-vitals",
            "web-analytics-ai-agent-traffic",
            "web-analytics-audience",
            "web-analytics-daily-visitors",
          ]
        `)
        expect(new Set(prompts.map((prompt) => prompt.name)).size).toBe(prompts.length)
        const goalPrompt = prompts.find((prompt) => prompt.name === 'web-analytics-goal-conversion-by-channel')!
        expect(goalPrompt.arguments?.map((argument) => argument.name)).toEqual(['goal'])
        expect(goalPrompt.messages).toEqual([
            {
                role: 'user',
                content: {
                    type: 'text',
                    text: expect.stringMatching(/^Which channels bring the most conversions to my goal\?\n\n/),
                },
            },
        ])
    })
})
