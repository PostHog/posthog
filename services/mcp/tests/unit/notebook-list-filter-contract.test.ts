import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/notebooks'

// The notebook list endpoint filters on more query params than it declared to drf-spectacular, and an
// undeclared filter never reaches the generated schema. The description promised a title search that
// callers had no way to send, so the documented path was unusable.
describe('notebooks-list filter contract', () => {
    const schema = GENERATED_TOOLS['notebooks-list']!().schema

    it.each(['search', 'contains', 'created_by', 'last_modified_by', 'date_from', 'date_to', 'user'])(
        'accepts the %s filter',
        (param) => {
            expect(Object.keys(schema.shape)).toContain(param)
        }
    )
})
