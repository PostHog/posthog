import type { WarehouseSuggestionApi } from './generated/api.schemas'
import { subjectUrl } from './subjectUrl'

function suggestion(overrides: Partial<WarehouseSuggestionApi>): WarehouseSuggestionApi {
    return {
        kind: 'certify',
        subject_kind: 'table',
        subject_id: 'table-1',
        subject_source_id: null,
        subject_schema_id: null,
        payload: { subject_name: 'stripe_charges' },
        ...overrides,
    } as WarehouseSuggestionApi
}

describe('subjectUrl', () => {
    it.each<[string, WarehouseSuggestionApi, Parameters<typeof subjectUrl>[1], string]>([
        [
            'a view on its model page',
            suggestion({ subject_kind: 'saved_query', subject_id: 'view-1' }),
            undefined,
            '/models/view-1?lookup=saved_query',
        ],
        [
            'a view on the model tab it was asked for',
            suggestion({ subject_kind: 'saved_query', subject_id: 'view-1' }),
            'materialization',
            '/models/view-1/materialization?lookup=saved_query',
        ],
        [
            'a synced table on its source schema page',
            suggestion({ subject_source_id: 'source-1', subject_schema_id: 'schema-1' }),
            undefined,
            '/data-management/sources/managed-source-1/schemas/schema-1',
        ],
        [
            'a table no source syncs on its own source page',
            suggestion({}),
            undefined,
            '/data-management/sources/self-managed-table-1/schemas',
        ],
    ])('opens %s', (_name, input, tab, url) => {
        expect(subjectUrl(input, tab)).toEqual(url)
    })
})
