import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    hogFlowsUserBlastRadiusCreate,
    workflowPreviousRecipientsCreate,
} from 'products/workflows/frontend/generated/api'

import { MessageAudience } from './messageAudience'
import { checkPreviousRecipients } from './previousRecipients'

jest.mock('products/workflows/frontend/generated/api', () => ({
    workflowPreviousRecipientsCreate: jest.fn(),
    hogFlowsUserBlastRadiusCreate: jest.fn(),
}))

const audience: MessageAudience = {
    source: 'early_access',
    sourceRecord: 'early_access:abc',
    sourceRecordName: 'Dark mode',
    properties: [{ key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsSet }],
}
const LEFT_OUT = { key: 'id', type: PropertyFilterType.Cohort, value: 77, operator: PropertyOperator.NotIn }

describe('checkPreviousRecipients', () => {
    it.each<{ case: string; counts: [number, number] | Error; expected: object }>([
        { case: 'some people overlap', counts: [10, 6], expected: { kind: 'some', skipped: 4 } },
        { case: 'the counts stay equal', counts: [10, 10], expected: { kind: 'some', skipped: 0 } },
        { case: 'the counts fail', counts: new Error('timeout'), expected: { kind: 'some', skipped: null } },
        { case: 'everyone overlaps', counts: [3, 0], expected: { kind: 'everyone', skipped: 3 } },
    ])('keeps the saved exclusion when $case', async ({ counts, expected }) => {
        jest.mocked(workflowPreviousRecipientsCreate).mockResolvedValue({ cohort_id: 77, people: 4 } as never)
        jest.mocked(hogFlowsUserBlastRadiusCreate).mockReset()
        if (counts instanceof Error) {
            jest.mocked(hogFlowsUserBlastRadiusCreate).mockRejectedValue(counts)
        } else {
            for (const affected of counts) {
                jest.mocked(hogFlowsUserBlastRadiusCreate).mockResolvedValueOnce({ affected } as never)
            }
        }

        const check = await checkPreviousRecipients('1', audience)

        expect(check).toMatchObject(expected)
        if (check.kind === 'some') {
            expect(check.audience.properties).toContainEqual(expect.objectContaining(LEFT_OUT))
        }
    })

    it('keeps the saved exclusion when a count never answers', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(workflowPreviousRecipientsCreate).mockResolvedValue({ cohort_id: 77, people: 4 } as never)
            jest.mocked(hogFlowsUserBlastRadiusCreate)
                .mockReset()
                .mockReturnValue(new Promise(() => {}))

            const check = checkPreviousRecipients('1', audience)
            await jest.advanceTimersByTimeAsync(5000)

            expect(await check).toMatchObject({ kind: 'some', skipped: null })
        } finally {
            jest.useRealTimers()
        }
    })
})
