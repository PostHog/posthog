import { MAX_AUTO_GROW_WIDTH, MIN_COLUMN_WIDTH, ResizableColumnSpec, resolveColumnWidths } from './columnWidths'

describe('resolveColumnWidths', () => {
    const specs: ResizableColumnSpec[] = [
        { key: 'service', width: 200 },
        { key: 'name', width: 320, grow: true },
        { key: 'errors', width: 80 },
    ]

    it('uses the default widths when nothing is stored', () => {
        const { widths, totalWidth } = resolveColumnWidths(specs, undefined, null, 600)
        expect(widths).toEqual({ service: 200, name: 320, errors: 80 })
        expect(totalWidth).toEqual(600)
    })

    it('gives leftover space to the growing column', () => {
        const { widths } = resolveColumnWidths(specs, undefined, null, 700)
        expect(widths.name).toEqual(420)
        expect(widths.service).toEqual(200)
    })

    it('caps how wide the growing column gets on a wide screen', () => {
        const { widths, totalWidth } = resolveColumnWidths(specs, undefined, null, 2560)
        expect(widths.name).toEqual(MAX_AUTO_GROW_WIDTH)
        expect(totalWidth).toBeLessThan(2560)
    })

    it('stops growing a column once it has a stored width, so a drag is not undone', () => {
        const { widths } = resolveColumnWidths(specs, { name: 260 }, null, 2560)
        expect(widths.name).toEqual(260)
    })

    it('prefers the live drag width over the stored width', () => {
        const { widths } = resolveColumnWidths(specs, { service: 200 }, { columnKey: 'service', width: 340 }, 2560)
        expect(widths.service).toEqual(340)
    })

    it('never renders a column narrower than the minimum', () => {
        const { widths } = resolveColumnWidths(specs, { service: 10 }, null, 600)
        expect(widths.service).toEqual(MIN_COLUMN_WIDTH)
    })

    it.each([NaN, Infinity, undefined as unknown as number])(
        'falls back to the default width for a stored %p',
        (stored) => {
            const { widths } = resolveColumnWidths(specs, { service: stored }, null, 600)
            expect(widths.service).toEqual(200)
        }
    )
})
