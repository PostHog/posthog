import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/notebooks'

// A filter the list view does not declare to drf-spectacular never reaches the generated schema, so an
// agent has no way to send it however well the tool description documents it.
describe('notebooks-list filter contract', () => {
    const schema = GENERATED_TOOLS['notebooks-list']!().schema

    it.each(['search', 'contains', 'created_by', 'last_modified_by', 'date_from', 'date_to', 'user'])(
        'accepts the %s filter',
        (param) => {
            expect(Object.keys(schema.shape)).toContain(param)
        }
    )
})
