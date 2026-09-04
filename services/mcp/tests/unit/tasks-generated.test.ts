import { describe, expect, it } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'

describe('Generated task tools', () => {
    it('does not expose immediate run inputs on tasks-create', () => {
        const schema = GENERATED_TOOL_MAP['tasks-create']!().schema

        expect(schema.parse({ description: 'Do work', branch: 'main', start_run: true })).toEqual({
            description: 'Do work',
        })
    })

    it('requires UUIDs for tasks-run-create identifiers', () => {
        const schema = GENERATED_TOOL_MAP['tasks-run-create']!().schema

        expect(() => schema.parse({ id: 'not-a-uuid' })).toThrow()
        expect(() => schema.parse({ id: '00000000-0000-4000-8000-000000000001', resume_from_run_id: 'bad' })).toThrow()
    })

    it('forces tasks-run-create to background mode', () => {
        const schema = GENERATED_TOOL_MAP['tasks-run-create']!().schema

        expect(schema.parse({ id: '00000000-0000-4000-8000-000000000001', mode: 'interactive' })).toMatchObject({
            mode: 'background',
            run_source: 'agent',
        })
    })
})
