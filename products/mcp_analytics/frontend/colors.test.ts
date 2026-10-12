import { DEFAULT_CHART_COLORS } from '@posthog/quill-charts'

import { AI_LAB_SHADES, labColor, modelColors } from './colors'

const theme = { colors: [...DEFAULT_CHART_COLORS], axisColor: '#888888' }

describe('colors', () => {
    it.each([
        ['Anthropic', AI_LAB_SHADES.Anthropic[2]],
        ['Open weights', AI_LAB_SHADES['Open weights'][2]],
        ['Other', theme.axisColor],
    ])('uses the main shade for the %s lab', (lab, color) => {
        expect(labColor(theme, lab)).toBe(color)
    })

    it.each([
        [['claude-sonnet-4-5', 'claude-3-5-sonnet']],
        [['claude-opus-4-1', 'claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4', 'claude-sonnet-4']],
        [['gpt-5', 'gpt-4o', 'o3-mini']],
        [
            [
                'claude-opus-5-5',
                'claude-fable-5-1',
                'claude-sonnet-5-5',
                'claude-sonnet-5',
                'claude-opus-5',
                'claude-haiku-5',
                'claude-opus-4-8',
            ],
        ],
    ])('gives every model of one lab its own shade: %j', (models) => {
        const colors = modelColors(theme, models)
        expect(new Set(models.map((model) => colors.get(model))).size).toBe(models.length)
    })

    it('uses the lab color for the only model of a lab', () => {
        expect(modelColors(theme, ['gemini-2.5-pro']).get('gemini-2.5-pro')).toBe(labColor(theme, 'Google'))
    })

    it('spreads models over the whole ramp, darkest first', () => {
        const colors = modelColors(theme, ['claude-sonnet-4-5', 'gpt-5', 'claude-opus-4-1', 'claude-haiku-4-5'])
        expect(['claude-sonnet-4-5', 'claude-opus-4-1', 'claude-haiku-4-5'].map((model) => colors.get(model))).toEqual([
            AI_LAB_SHADES.Anthropic[0],
            AI_LAB_SHADES.Anthropic[2],
            AI_LAB_SHADES.Anthropic[4],
        ])
    })

    it('keeps neutral buckets gray and gives models without a lab a palette color', () => {
        const colors = modelColors(theme, ['Unknown', 'Other', 'example-custom-model'])
        expect(colors.get('Unknown')).toBe(theme.axisColor)
        expect(colors.get('Other')).toBe(theme.axisColor)
        expect(theme.colors).toContain(colors.get('example-custom-model'))
    })
})
