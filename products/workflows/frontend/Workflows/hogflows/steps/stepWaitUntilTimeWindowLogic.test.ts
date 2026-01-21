import { resetContext } from 'kea'
import { expectLogic, partial, testUtilsPlugin } from 'kea-test-utils'

import { uuid } from 'lib/utils'

import { initKeaTests } from '~/test/init'
import { WeekdayType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { getWaitUntilTimeWindowDescription, stepWaitUntilTimeWindowLogic } from './stepWaitUntilTimeWindowLogic'

describe('stepWaitUntilTimeWindowLogic', () => {
    let logic: ReturnType<typeof stepWaitUntilTimeWindowLogic.build>

    beforeEach(() => {
        initKeaTests()

        resetContext({
            plugins: [testUtilsPlugin],
        })

        workflowLogic.mount()

        logic = stepWaitUntilTimeWindowLogic({ workflowLogicProps: workflowLogic.props })
        logic.mount()
    })

    const setupInitialAction = async (
        initialDescription: string,
        configOverrides?: {
            use_person_timezone?: boolean
            fallback_timezone?: string | null
        }
    ): Promise<HogFlowAction> => {
        const action = {
            id: `wait_action_${uuid()}`,
            type: 'wait_until_time_window',
            name: 'Wait until time window',
            description: initialDescription,
            config: {
                day: 'weekday',
                time: ['09:00', '17:00'],
                timezone: 'UTC',
                use_person_timezone: configOverrides?.use_person_timezone ?? false,
                fallback_timezone: configOverrides?.fallback_timezone ?? null,
            },
            created_at: Date.now(),
            updated_at: Date.now(),
        } as HogFlowAction

        await expectLogic(workflowLogic, () => {
            workflowLogic.actions.setWorkflowInfo({
                actions: [...workflowLogic.values.workflow.actions, action],
            })
        }).toDispatchActions(['setWorkflowInfo'])

        await expectLogic(workflowLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: initialDescription })]),
            }),
        })

        return action
    }
    it('should update the description when day is changed', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { day: 'weekend' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: 'Wait until weekends between 09:00 and 17:00 (UTC).',
                    }),
                ]),
            }),
        })
    })

    it('should update the description when time is changed', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { time: ['10:00', '18:00'] })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: 'Wait until weekdays between 10:00 and 18:00 (UTC).',
                    }),
                ]),
            }),
        })
    })

    it('should update the description when timezone is changed', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { timezone: 'America/New_York' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: 'Wait until weekdays between 09:00 and 17:00 (America/New_York).',
                    }),
                ]),
            }),
        })
    })

    it('should not update the description when the description is customized', async () => {
        const customDescription = 'Custom description, dont delete me pls :('
        const action = await setupInitialAction(customDescription)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { day: 'weekend' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: customDescription })]),
            }),
        })
    })

    it('should update the description when use_person_timezone is enabled', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { use_person_timezone: true })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: "Wait until weekdays between 09:00 and 17:00 (person's timezone, fallback: UTC).",
                    }),
                ]),
            }),
        })
    })

    it('should update the description with fallback timezone when use_person_timezone is enabled', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription(
            'weekday',
            ['09:00', '17:00'],
            'UTC',
            true,
            'Europe/London'
        )
        const action = await setupInitialAction(initialDesc, {
            use_person_timezone: true,
            fallback_timezone: 'Europe/London',
        })

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { fallback_timezone: 'America/New_York' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description:
                            "Wait until weekdays between 09:00 and 17:00 (person's timezone, fallback: America/New_York).",
                    }),
                ]),
            }),
        })
    })
})

describe('getWaitUntilTimeWindowDescription', () => {
    it.each([
        {
            name: 'generates description without person timezone',
            day: 'weekday' as const,
            time: ['09:00', '17:00'] as [string, string],
            timezone: 'UTC',
            usePersonTimezone: false,
            fallbackTimezone: null,
            expected: 'Wait until weekdays between 09:00 and 17:00 (UTC).',
        },
        {
            name: 'generates description with person timezone and fallback',
            day: 'any' as const,
            time: 'any' as const,
            timezone: 'UTC',
            usePersonTimezone: true,
            fallbackTimezone: 'Europe/London',
            expected: "Wait until any day at any time (person's timezone, fallback: Europe/London).",
        },
        {
            name: 'uses timezone as fallback when no fallback_timezone specified',
            day: 'weekend' as const,
            time: ['10:00', '18:00'] as [string, string],
            timezone: 'America/Chicago',
            usePersonTimezone: true,
            fallbackTimezone: null,
            expected: "Wait until weekends between 10:00 and 18:00 (person's timezone, fallback: America/Chicago).",
        },
        {
            name: 'handles custom days with person timezone',
            day: ['monday', 'wednesday', 'friday'] as WeekdayType[],
            time: ['08:00', '12:00'] as [string, string],
            timezone: 'Asia/Tokyo',
            usePersonTimezone: true,
            fallbackTimezone: 'Asia/Tokyo',
            expected:
                "Wait until Monday, Wednesday, Friday between 08:00 and 12:00 (person's timezone, fallback: Asia/Tokyo).",
        },
    ])('$name', ({ day, time, timezone, usePersonTimezone, fallbackTimezone, expected }) => {
        const result = getWaitUntilTimeWindowDescription(day, time, timezone, usePersonTimezone, fallbackTimezone)
        expect(result).toBe(expected)
    })
})
