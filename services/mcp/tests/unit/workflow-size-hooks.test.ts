import { describe, expect, it } from 'vitest'

import type { Context } from '@/tools/types'
import workflowSizeHooks, { splitSuggestionNote } from '@/tools/workflows/workflowSizeHooks'

const steps = (count: number): { id: string }[] =>
    Array.from({ length: count }, (_, index) => ({ id: `step-${index}` }))

describe('workflowSizeHooks', () => {
    it.each([
        { name: 'at the limit', workflow: { id: 'wf', actions: steps(50), draft: null }, note: null },
        { name: 'above the limit', workflow: { id: 'wf', actions: steps(51), draft: null }, note: 51 },
        {
            name: 'a staged draft above the limit',
            workflow: { id: 'wf', actions: steps(10), draft: { actions: steps(60) } },
            note: 60,
        },
        { name: 'a result without actions', workflow: { id: 'wf' }, note: null },
    ])('adds the split note for $name', ({ workflow, note }) => {
        const result = workflowSizeHooks.afterResponse({} as Context, {}, workflow)

        if (note === null) {
            expect(result).toBe(workflow)
        } else {
            expect(result).toEqual({ ...workflow, _agentNote: splitSuggestionNote(note) })
        }
    })
})
