import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'

describe('generated query wrappers', () => {
    it('accepts behavioral filters for trends queries', () => {
        const tool = GENERATED_TOOLS['query-trends']!()

        expect(
            tool.schema.safeParse({
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                properties: [
                    {
                        type: 'behavioral',
                        value: 'performed_event',
                        key: 'user invited',
                        event_type: 'events',
                        negation: true,
                        time_value: 30,
                        time_interval: 'day',
                    },
                ],
            }).success
        ).toBe(true)
    })
})
