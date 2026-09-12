import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/customer_analytics'

// The account sub-resource tools take the account UUID as `id`, but the sibling nested tools
// take `account_id`. Production traces show agents carrying `account_id` over, which is the
// dominant validation failure for both. The alias must normalize to `id` or those come back.
describe('account id aliases', () => {
    const ALIAS_KEYS = ['account_id', 'accountId'] as const
    const ACCOUNT_UUID = '01a06c39-8bc8-770f-a945-a926dbafd653'

    describe.each([['accounts-summaries-list'], ['accounts-meetings-list']])(
        '%s normalizes aliases to `id`',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema

            it.each([
                ['id', { id: ACCOUNT_UUID }],
                ['account_id', { account_id: ACCOUNT_UUID }],
                ['accountId', { accountId: ACCOUNT_UUID }],
            ])('accepts %s', (_label, input) => {
                const result = schema.safeParse(input)
                expect(result.success).toBe(true)
                const data = result.data as Record<string, unknown>
                expect(data.id).toEqual(ACCOUNT_UUID)
                for (const alias of ALIAS_KEYS) {
                    expect(data).not.toHaveProperty(alias)
                }
            })

            it('still rejects a call with no account identifier', () => {
                expect(schema.safeParse({}).success).toBe(false)
            })
        }
    )
})
