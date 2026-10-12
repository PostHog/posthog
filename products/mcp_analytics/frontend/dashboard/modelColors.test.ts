import { DEFAULT_CHART_COLORS } from '@posthog/quill-charts'

import { labColor, modelColor } from './modelColors'

const theme = { colors: [...DEFAULT_CHART_COLORS], axisColor: '#888888' }

describe('modelColor', () => {
    it.each([
        ['Anthropic', '#d97757'],
        ['OpenAI', '#74aa9c'],
        ['Google', '#4285f4'],
        ['xAI', '#e4a604'],
        ['Cursor', '#a56eff'],
        ['Open weights', '#fe729e'],
        ['Other', theme.axisColor],
    ])('uses a stable color for %s', (lab, color) => {
        expect(labColor(theme, lab)).toBe(color)
    })

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

    it('uses distinct shades for models from the same AI lab', () => {
        expect(modelColor(theme, 'gpt-4o')).not.toEqual(modelColor(theme, 'gpt-5'))
        expect(modelColor(theme, 'claude-sonnet-4')).not.toEqual(modelColor(theme, 'claude-opus-4'))
    })
})
