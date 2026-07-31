import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { ReadDataSchemaSchema } from '@/schema/tool-inputs'

describe('read-data-schema event discovery contract', () => {
    it('discloses that event discovery only searches the last 30 days', () => {
        const schema = JSON.stringify(z.toJSONSchema(ReadDataSchemaSchema, { io: 'input' }))

        expect(schema).toContain('last 30 days')
    })
})
