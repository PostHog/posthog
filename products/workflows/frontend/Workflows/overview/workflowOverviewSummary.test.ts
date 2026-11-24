import { PERSON_FREQUENCY_OPTIONS } from '../hogflows/registry/triggers/triggerTypeRegistry'
import type { HogFlow } from '../hogflows/types'
import { frequencySummary } from './workflowOverviewSummary'

const [, oneTimePerPeriod, oncePerCalendarDay] = PERSON_FREQUENCY_OPTIONS

const withMasking = (hash: string | null, ttl: number | null): Pick<HogFlow, 'trigger' | 'trigger_masking'> => ({
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    trigger_masking: hash ? { hash, ttl, threshold: null, bytecode: [] } : null,
})

describe('frequencySummary', () => {
    test.each([
        ['no masking', withMasking(null, null), 'Every time the trigger fires'],
        ['one time with a period', withMasking(oneTimePerPeriod.value, 90 * 24 * 60 * 60), 'One time per 90 days'],
        ['one time with no period', withMasking(oneTimePerPeriod.value, null), 'One time ever'],
        [
            'calendar day ignores the stored ttl',
            withMasking(oncePerCalendarDay.value, 24 * 60 * 60),
            'Once per calendar day',
        ],
        ['custom rule with a period', withMasking('{event.uuid}', 30 * 60), 'Limited by a custom rule per 30 minutes'],
    ])('%s', (_, workflow, expected) => {
        expect(frequencySummary(workflow)).toEqual(expected)
    })
})
