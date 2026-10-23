import type { WarehouseSuggestionApi } from './generated/api.schemas'
import { subjectUrl } from './subjectUrl'

function tableSuggestion(name: string): WarehouseSuggestionApi {
    return {
        kind: 'certify',
        subject_kind: 'table',
        subject_id: 'table-1',
        payload: { subject_name: name },
    } as WarehouseSuggestionApi
}

function previewQuery(url: string): string | null {
    return new URL(url, 'https://example.com').searchParams.get('open_query')
}

describe('subjectUrl', () => {
    it.each([
        ['a plain table name', 'stripe_charges', 'SELECT * FROM stripe_charges LIMIT 100'],
        ['a dotted source table name', 'demo.orders', 'SELECT * FROM demo.orders LIMIT 100'],
        [
            'a stored name that starts and ends with quotes',
            '"x" UNION SELECT * FROM persons --"',
            'SELECT * FROM `"x" UNION SELECT * FROM persons --"` LIMIT 100',
        ],
    ])('previews %s as one table', (_name, tableName, query) => {
        expect(previewQuery(subjectUrl(tableSuggestion(tableName)))).toEqual(query)
    })
})
