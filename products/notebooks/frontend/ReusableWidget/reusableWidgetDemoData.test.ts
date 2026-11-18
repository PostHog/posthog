import type { WidgetFrameApi } from '../generated/api.schemas'
import { demoRowsAsJSON, parseDemoRows } from './reusableWidgetDemoData'

const columns = [
    { name: 'plan', type: 'String' },
    { name: 'revenue', type: 'Float64' },
]

describe('reusableWidgetDemoData', () => {
    it('round trips demo rows and restores contract order when JSON keys are reordered', () => {
        const frame = {
            columns,
            rows: [
                ['Starter', 120],
                ['Growth', null],
            ],
        } as WidgetFrameApi
        expect(parseDemoRows(demoRowsAsJSON(frame), columns)).toEqual(frame.rows)
        expect(parseDemoRows('[{"revenue":120,"plan":"Starter"}]', columns)).toEqual([['Starter', 120]])
        expect(parseDemoRows('[]', columns)).toEqual([])
    })

    it.each([
        ['not JSON', 'valid JSON'],
        ['{}', 'array'],
        ['[null]', 'Row 1 must be an object'],
        ['[["Starter",120]]', 'Row 1 must be an object'],
        ['[{"plan":"Starter"}]', 'exactly these columns'],
        ['[{"plan":"Starter","revenue":120,"extra":true}]', 'exactly these columns'],
        [JSON.stringify(Array(21).fill({ plan: 'Starter', revenue: 120 })), 'at most 20'],
    ])('rejects invalid demo data: %s', (text, message) => {
        expect(() => parseDemoRows(text, columns)).toThrow(message)
    })
})
