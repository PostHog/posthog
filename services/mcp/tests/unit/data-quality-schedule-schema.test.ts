import { describe, expect, it } from 'vitest'

import { getToolByName } from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/data_quality'

describe('Generated data-quality-check-schedule tool', () => {
    it('requires the subject on the schedule schema (PATCH optionality stripped)', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'data-quality-check-schedule')

        // The endpoint names its subject in the body and rejects a request that omits it, but a
        // PATCH marks every body field optional in OpenAPI — the schema must re-require both so
        // the agent cannot send an interval alone and hit a backend 400.
        expect(() => tool.schema.parse({ interval: '6hour' })).toThrow()
        expect(() => tool.schema.parse({ subject_type: 'metric', interval: '6hour' })).toThrow()
        expect(
            tool.schema.parse({
                subject_type: 'metric',
                subject_uuid: '0199c0de-0000-7000-8000-00000000beef',
                interval: '6hour',
            })
        ).toEqual({
            subject_type: 'metric',
            subject_uuid: '0199c0de-0000-7000-8000-00000000beef',
            interval: '6hour',
        })
    })
})
