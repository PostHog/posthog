import { DEFAULT_CHART_COLORS } from '@posthog/quill-charts'

import { modelColor } from './modelColors'

const theme = { colors: [...DEFAULT_CHART_COLORS], axisColor: '#888888' }

describe('modelColor', () => {
    it.each([
        ['gpt-4o', 'openai/gpt-4o'],
        ['gpt-4o', 'openrouter/openai/gpt-4o'],
        ['gpt-4o', 'openai.gpt-4o'],
        ['claude-sonnet-4', 'us.anthropic.claude-sonnet-4'],
        ['gemini-2.5-pro', 'google/gemini-2.5-pro'],
        ['grok-3', 'cursor-grok-3'],
        ['grok-3', ' Cursor Grok 3 '],
        ['glm-4', 'z-ai/glm-4'],
        ['o3-mini', 'openai/o3-mini'],
    ])('keeps %s the same color as %s', (model, alias) => {
        expect(modelColor(theme, alias)).toEqual(modelColor(theme, model))
    })

    it('keeps neutral buckets separate from models without a recognized family', () => {
        expect(modelColor(theme, 'Unknown')).toBe(theme.axisColor)
        expect(modelColor(theme, 'Other')).toBe(theme.axisColor)
        expect(modelColor(theme, 'example-custom-model')).not.toBe(theme.axisColor)
    })
})
