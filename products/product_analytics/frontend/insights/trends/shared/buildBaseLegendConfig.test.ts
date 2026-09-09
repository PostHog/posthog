import { buildBaseLegendConfig } from './buildBaseLegendConfig'

const renderItem = jest.fn()

describe('buildBaseLegendConfig', () => {
    it.each([
        { name: 'right', legendPosition: 'right', expected: 'right' },
        { name: 'left', legendPosition: 'left', expected: 'left' },
        { name: 'unset (defaults to right)', legendPosition: undefined, expected: 'right' },
    ])('positions the legend $name', ({ legendPosition, expected }) => {
        const config = buildBaseLegendConfig({ show: true, legendPosition, canEditInsight: true })

        expect(config.position).toBe(expected)
    })

    it.each([
        {
            name: 'an editable legend gets the row menu',
            canEditInsight: true,
            inSharedMode: false,
            expectedInteractive: true,
            expectedRenderItem: renderItem,
        },
        {
            name: 'a read-only legend gets neither toggling nor the row menu',
            canEditInsight: false,
            inSharedMode: false,
            expectedInteractive: false,
            expectedRenderItem: undefined,
        },
        {
            name: 'a shared-mode legend gets neither either',
            canEditInsight: true,
            inSharedMode: true,
            expectedInteractive: false,
            expectedRenderItem: undefined,
        },
    ])('$name', ({ canEditInsight, inSharedMode, expectedInteractive, expectedRenderItem }) => {
        const config = buildBaseLegendConfig({
            show: true,
            legendPosition: 'right',
            canEditInsight,
            inSharedMode,
            renderItem,
        })

        expect(config.interactive).toBe(expectedInteractive)
        expect(config.renderItem).toBe(expectedRenderItem)
    })
})
