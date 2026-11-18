import type { Span } from '../../types'
import {
    addSpanColumn,
    availableBuiltInColumns,
    DEFAULT_SPAN_COLUMNS,
    moveSpanColumn,
    normalizeSpanColumns,
    removeSpanColumn,
    SpanColumnConfig,
    spanAttributeValue,
    spanColumnKey,
    toggleSpanAttributeColumn,
    toSpanColumnSpecs,
} from './spanColumns'

describe('spanColumns', () => {
    const attributeColumn: SpanColumnConfig = { type: 'attribute', attributeKey: 'http.target' }

    const span = (overrides: Partial<Span>): Span => ({ attributes: {}, resource_attributes: {}, ...overrides }) as Span

    it('keeps an attribute column distinct from a built-in of the same name', () => {
        expect(spanColumnKey({ type: 'attribute', attributeKey: 'name' })).not.toEqual(spanColumnKey({ type: 'name' }))
    })

    it('reads an attribute from the span first, then the resource', () => {
        const key = 'service.version'
        expect(spanAttributeValue(span({ attributes: { [key]: '2.1' } }), key)).toEqual('2.1')
        expect(spanAttributeValue(span({ resource_attributes: { [key]: '1.0' } }), key)).toEqual('1.0')
        expect(
            spanAttributeValue(span({ attributes: { [key]: '2.1' }, resource_attributes: { [key]: '1.0' } }), key)
        ).toEqual('2.1')
        expect(spanAttributeValue(span({}), key)).toEqual('')
    })

    it('does not add a column the table already shows', () => {
        const columns = addSpanColumn(DEFAULT_SPAN_COLUMNS, { type: 'name' })
        expect(columns).toEqual(DEFAULT_SPAN_COLUMNS)
    })

    it('offers only the built-in columns that are not on screen', () => {
        expect(availableBuiltInColumns(DEFAULT_SPAN_COLUMNS)).toEqual([])
        expect(availableBuiltInColumns(removeSpanColumn(DEFAULT_SPAN_COLUMNS, 'kind'))).toEqual(['kind'])
    })

    it('adds an attribute column on the first toggle and removes it on the second', () => {
        const added = toggleSpanAttributeColumn(DEFAULT_SPAN_COLUMNS, 'http.target')
        expect(added).toContainEqual(attributeColumn)
        expect(toggleSpanAttributeColumn(added, 'http.target')).toEqual(DEFAULT_SPAN_COLUMNS)
    })

    it.each([
        ['up', 'timestamp', ['timestamp', 'name']],
        ['down', 'name', ['timestamp', 'name']],
    ] as const)('leaves the list untouched moving %s past the end', (direction, key, expected) => {
        const columns: SpanColumnConfig[] = [{ type: 'timestamp' }, { type: 'name' }]
        expect(moveSpanColumn(columns, key, direction).map(spanColumnKey)).toEqual(expected)
    })

    it('moves a column one place', () => {
        const columns: SpanColumnConfig[] = [{ type: 'timestamp' }, { type: 'name' }, attributeColumn]
        expect(moveSpanColumn(columns, 'attr:http.target', 'up').map(spanColumnKey)).toEqual([
            'timestamp',
            'attr:http.target',
            'name',
        ])
    })

    it.each([
        ['a type this version cannot render', [{ type: 'timestamp' }, { type: 'retiredColumn' }], ['timestamp']],
        ['an attribute column with no key', [{ type: 'timestamp' }, { type: 'attribute' }], ['timestamp']],
        ['a duplicate', [{ type: 'timestamp' }, { type: 'timestamp' }], ['timestamp']],
        ['a non-object entry', [{ type: 'timestamp' }, null, 'timestamp'], ['timestamp']],
    ])('drops %s from persisted columns', (_case, stored, expected) => {
        expect(normalizeSpanColumns(stored).map(spanColumnKey)).toEqual(expected)
    })

    it.each([
        ['nothing persisted', undefined],
        ['a value that is not a list', { type: 'timestamp' }],
        ['a list with nothing renderable left', [{ type: 'retiredColumn' }]],
    ])('falls back to the default columns for %s', (_case, stored) => {
        expect(normalizeSpanColumns(stored)).toEqual(DEFAULT_SPAN_COLUMNS)
    })

    it('appends the structural columns after the configured ones', () => {
        const specs = toSpanColumnSpecs([{ type: 'timestamp' }], { showSpanErrors: true })
        expect(specs.map((spec) => spec.key)).toEqual(['timestamp', 'spanErrors', 'actions'])
        expect(toSpanColumnSpecs([{ type: 'timestamp' }], { showSpanErrors: false }).map((spec) => spec.key)).toEqual([
            'timestamp',
            'actions',
        ])
    })

    it('grows the last configured column when name is not on screen, so the table still fills the viewport', () => {
        const withName = toSpanColumnSpecs(DEFAULT_SPAN_COLUMNS, { showSpanErrors: false })
        expect(withName.find((spec) => spec.grow)?.key).toEqual('name')

        const withoutName = toSpanColumnSpecs([{ type: 'timestamp' }, attributeColumn], { showSpanErrors: false })
        expect(withoutName.find((spec) => spec.grow)?.key).toEqual('attr:http.target')
    })
})
