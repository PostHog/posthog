import { parseSeasonalChecklist } from './seasonalChecklist'

const item = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
    key: 'alerts',
    title: 'Get alerted when a key metric drops',
    description: 'An alert checks the metric every hour.',
    icon: 'bell',
    actionLabel: 'Set up alert',
    url: '/insights',
    ...overrides,
})

const payload = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
    campaign: 'winter-checklist',
    title: 'Before you log off',
    description: 'Four things to set up before a break.',
    accessories: ['xmas-hat'],
    snow: true,
    items: [item()],
    ...overrides,
})

describe('parseSeasonalChecklist', () => {
    it('fills the optional fields of a minimal payload', () => {
        expect(parseSeasonalChecklist(payload({ items: [item({ actionLabel: undefined, url: undefined })] }))).toEqual({
            campaign: 'winter-checklist',
            title: 'Before you log off',
            description: 'Four things to set up before a break.',
            reason: null,
            badge: null,
            bubble: 'Before you log off',
            doneTitle: 'Before you log off',
            doneDescription: 'Four things to set up before a break.',
            accessories: ['xmas-hat'],
            snow: true,
            lights: false,
            items: [
                {
                    key: 'alerts',
                    title: 'Get alerted when a key metric drops',
                    description: 'An alert checks the metric every hour.',
                    icon: 'bell',
                    actionLabel: null,
                    url: null,
                },
            ],
        })
    })

    it('accepts an in-app path and an https link', () => {
        const parsed = parseSeasonalChecklist(
            payload({ items: [item(), item({ key: 'docs', url: 'https://posthog.com/docs' })] })
        )
        expect(parsed?.items.map((i) => i.url)).toEqual(['/insights', 'https://posthog.com/docs'])
    })

    it.each([
        ['no payload', undefined],
        ['a string payload', 'winter'],
        ['no campaign', payload({ campaign: '' })],
        ['a number as the badge', payload({ badge: 4 })],
        ['no items', payload({ items: [] })],
        ['too many items', payload({ items: Array.from({ length: 7 }, (_, i) => item({ key: `k${i}` })) })],
        ['duplicate item keys', payload({ items: [item(), item()] })],
        ['an unknown accessory', payload({ accessories: ['crown'] })],
        ['snow as a string', payload({ snow: 'yes' })],
        ['an unknown icon', payload({ items: [item({ icon: 'snowman' })] })],
        ['a label with no link', payload({ items: [item({ url: undefined })] })],
        ['a link with no label', payload({ items: [item({ actionLabel: undefined })] })],
        ['a javascript link', payload({ items: [item({ url: 'javascript:alert(1)' })] })],
        ['a protocol-relative link', payload({ items: [item({ url: '//example.com' })] })],
        ['a plain http link', payload({ items: [item({ url: 'http://example.com' })] })],
    ])('rejects %s', (_, value) => {
        expect(parseSeasonalChecklist(value)).toBeNull()
    })
})
