import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import { harnessColor } from './harnessRegistry'
import { AI_LAB_COLORS } from './modelColors'

const theme: ChartTheme = { ...buildTheme(), colors: ['#204080', '#804020'], axisColor: '#888888' }

describe('harnessColor', () => {
    it('keeps colors attached to harness names when their ranking changes', () => {
        const harnesses = ['OpenAI Codex', 'Claude Code', 'Claude Agent SDK', 'opencode', 'Example custom client']
        const colors = Object.fromEntries(harnesses.map((label) => [label, harnessColor(theme, label)]))
        const reorderedColors = Object.fromEntries(
            harnesses.toReversed().map((label) => [label, harnessColor(theme, label)])
        )

        expect(reorderedColors).toEqual(colors)
        expect(Object.values(colors).every(Boolean)).toBe(true)
    })

    it.each([
        ['Claude Code', 'Claude Agent SDK'],
        ['OpenAI Codex', 'ChatGPT'],
    ])('distinguishes %s from %s within the same family', (first, second) => {
        expect(harnessColor(theme, first)).not.toEqual(harnessColor(theme, second))
    })

    it.each([
        ['Claude Code', AI_LAB_COLORS.Anthropic],
        ['ChatGPT', AI_LAB_COLORS.OpenAI],
        ['Cursor', AI_LAB_COLORS.Cursor],
        ['Grok', AI_LAB_COLORS.xAI],
    ])('matches the %s harness to its AI lab color', (label, color) => {
        expect(harnessColor(theme, label)).toBe(color)
    })

    it.each(['Other', 'Unidentified client'])('keeps %s neutral with calls from identified harnesses', (label) => {
        expect(harnessColor(theme, label)).toBe(theme.axisColor)
        expect(harnessColor(theme, 'OpenAI Codex')).not.toBe(theme.axisColor)
    })

    it.each(['Claude Code', 'OpenAI Codex', 'Cursor', 'Grok', 'VS Code', 'CodeRabbit', 'Kimchi'])(
        'preserves the brand color for %s independently of the categorical palette',
        (label) => {
            expect(harnessColor({ ...theme, colors: [] }, label)).toBe(harnessColor(theme, label))
        }
    )

    it.each(['Notion', 'opencode', 'Windsurf'])('adapts the monochrome %s color to the chart theme', (label) => {
        expect(harnessColor(theme, label)).toBe(theme.axisColor)
        expect(harnessColor({ ...theme, axisColor: '#eeeeee' }, label)).toBe('#eeeeee')
    })

    it('uses the neutral color when the theme has no palette', () => {
        expect(harnessColor({ ...theme, colors: [] }, 'Example custom client')).toBe(theme.axisColor)
    })
})
