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
                'Other Anthropic models',
            ],
        ],
    ])('gives every model of one lab its own shade: %j', (models) => {
        const colors = modelColors(theme, models)
        expect(new Set(models.map((model) => colors.get(model))).size).toBe(models.length)
    })

    it('uses the lab color for the only model of a lab', () => {
        expect(modelColors(theme, ['gemini-2.5-pro']).get('gemini-2.5-pro')).toBe(labColor(theme, 'Google'))
    })

    it.each([
        [
            ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5'],
            [undefined, 2, undefined],
        ],
        [
            ['claude-opus-5-5', 'claude-fable-5-1', 'claude-sonnet-5-5', 'claude-sonnet-5'],
            [0, undefined, undefined, 4],
        ],
        [
            ['claude-opus-5-5', 'claude-fable-5-1', 'claude-sonnet-5-5', 'claude-sonnet-5', 'claude-haiku-5'],
            [0, 1, 2, 3, 4],
        ],
    ])('centers %j on the main shade, darkest first', (models, expectedShades) => {
        const colors = modelColors(theme, ['gpt-5', ...models])
        const shades = AI_LAB_SHADES.Anthropic
        models.forEach((model, rank) => {
            const shade = expectedShades[rank]
            if (shade === undefined) {
                expect(shades).not.toContain(colors.get(model))
            } else {
                expect(colors.get(model)).toBe(shades[shade])
            }
        })
    })

    it('keeps neutral buckets gray and gives models without a lab a palette color', () => {
        const colors = modelColors(theme, ['Unknown', 'Other', 'example-custom-model'])
        expect(colors.get('Unknown')).toBe(theme.axisColor)
        expect(colors.get('Other')).toBe(theme.axisColor)
        expect(theme.colors).toContain(colors.get('example-custom-model'))
    })
})
