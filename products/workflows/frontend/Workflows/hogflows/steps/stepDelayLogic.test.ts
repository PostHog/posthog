import { resetContext } from 'kea'
import { expectLogic, partial, testUtilsPlugin } from 'kea-test-utils'

import { uuid } from 'lib/utils/dom'

import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import {
    DelayActionConfig,
    DelayOffset,
    DelayProperty,
    buildDelayExpression,
    buildDelayOffset,
    getDelayDescription,
    parseDelayExpression,
    parseDelayOffset,
    stepDelayLogic,
} from './stepDelayLogic'

describe('stepDelayLogic', () => {
    let sdLogic: ReturnType<typeof stepDelayLogic.build>
    let wfLogic: ReturnType<typeof workflowLogic.build>

    beforeEach(() => {
        initKeaTests()

        resetContext({
            plugins: [testUtilsPlugin],
        })

        wfLogic = workflowLogic({ id: 'new' })
        wfLogic.mount()

        sdLogic = stepDelayLogic({ workflowLogicProps: wfLogic.props })
        sdLogic.mount()
    })

    const setupInitialDelayAction = async (
        initialDescription: string,
        config: DelayActionConfig = { delay_duration: '10m' }
    ): Promise<HogFlowAction> => {
        const delayAction = {
            id: `delay_action_${uuid()}`,
            type: 'delay',
            name: 'Delay',
            description: initialDescription,
            config,
            created_at: Date.now(),
            updated_at: Date.now(),
        } as HogFlowAction

        await expectLogic(wfLogic, () => {
            wfLogic.actions.setWorkflowInfo({
                actions: [...wfLogic.values.workflow.actions, delayAction],
            })
        }).toDispatchActions(['setWorkflowInfo'])

        await expectLogic(wfLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: initialDescription })]),
            }),
        })

        return delayAction
    }

    const configOf = (actionId: string): DelayActionConfig =>
        wfLogic.values.workflow.actions.find((a) => a.id === actionId)?.config as DelayActionConfig

    const descriptionOf = (actionId: string): string =>
        wfLogic.values.workflow.actions.find((a) => a.id === actionId)?.description ?? ''

    it('should update the description when the duration is changed', async () => {
        const delayAction = await setupInitialDelayAction(getDelayDescription({ delay_duration: '10m' }))

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayWorkflowActionConfig(delayAction.id, { delay_duration: '5m' })
        })
            .toDispatchActions(['setWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(sdLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: 'Wait for 5 minutes.' })]),
            }),
        })
    })

    it('should not update the description when the description is customized', async () => {
        const customDescription = 'Custom description, dont delete me pls :('
        const delayAction = await setupInitialDelayAction(customDescription)

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayWorkflowActionConfig(delayAction.id, { delay_duration: '5m' })
        })
            .toDispatchActions(['setWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(sdLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: customDescription })]),
            }),
        })
    })

    // A key the builder cannot read back leaves the picker blank on reload, so the user's choice looks
    // lost and re-picking silently overwrites it. Property keys carry $, spaces and quotes in practice.
    it.each([
        [{ source: 'person', key: 'expires_at' } as DelayProperty, 'person.properties.expires_at'],
        [{ source: 'event', key: 'scheduled_at' } as DelayProperty, 'event.properties.scheduled_at'],
        [{ source: 'person', key: '$trial_ends' } as DelayProperty, "person.properties['$trial_ends']"],
        [{ source: 'person', key: 'renews on' } as DelayProperty, "person.properties['renews on']"],
        [{ source: 'event', key: "o'clock" } as DelayProperty, "event.properties['o\\'clock']"],
    ])('%o round trips through %p', (property, expression) => {
        expect(buildDelayExpression(property)).toBe(expression)
        expect(parseDelayExpression(expression)).toEqual(property)
    })

    it('reads back no property for an expression the builder did not compose', () => {
        expect(parseDelayExpression('toDateTime(person.properties.a) + toIntervalDay(1)')).toBeNull()
    })

    // The sign carries the direction, and a zero offset must save nothing at all: '0d' would otherwise
    // reach the executor as a real offset and read back as "0 days before" in the step description.
    it.each([
        [{ amount: 1, unit: 'd', direction: 'before' } as DelayOffset, '-1d'],
        [{ amount: 2, unit: 'h', direction: 'after' } as DelayOffset, '2h'],
        [{ amount: 1.5, unit: 'd', direction: 'before' } as DelayOffset, '-1.5d'],
        [{ amount: 30, unit: 's', direction: 'after' } as DelayOffset, '30s'],
    ])('%o round trips through %p', (offset, serialized) => {
        expect(buildDelayOffset(offset)).toBe(serialized)
        expect(parseDelayOffset(serialized)).toEqual(offset)
    })

    it.each([[0], [-1], [NaN]])('saves no offset for an amount of %p', (amount) => {
        expect(buildDelayOffset({ amount, unit: 'd', direction: 'before' })).toBeUndefined()
    })

    // The API rejects a config carrying both modes, so a merge here would 400 every save.
    it('drops the duration when switching to a date, and the date when switching back', async () => {
        const delayAction = await setupInitialDelayAction(getDelayDescription({ delay_duration: '10m' }), {
            delay_duration: '10m',
            max_delay_duration: '7d',
        })

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayMode(delayAction.id, 'until')
        }).toFinishListeners()

        expect(configOf(delayAction.id)).toEqual({
            delay_until: { expression: '' },
            max_delay_duration: '7d',
        })

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayMode(delayAction.id, 'duration')
        }).toFinishListeners()

        expect(configOf(delayAction.id)).toEqual({ delay_duration: '10m' })
    })

    it('composes the expression and offset onto delay_until', async () => {
        const delayAction = await setupInitialDelayAction('', { delay_until: { expression: '' } })

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayProperty(delayAction.id, { source: 'person', key: 'expires_at' })
        }).toFinishListeners()

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayOffset(delayAction.id, { amount: 1, unit: 'd', direction: 'before' })
        }).toFinishListeners()

        expect(configOf(delayAction.id)).toEqual({
            delay_until: { expression: 'person.properties.expires_at', offset: '-1d' },
        })
        expect(descriptionOf(delayAction.id)).toBe('Wait until 1 day before expires_at.')
    })

    it('keeps a customized description when the mode changes', async () => {
        const customDescription = 'Nudge them before renewal'
        const delayAction = await setupInitialDelayAction(customDescription)

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayMode(delayAction.id, 'until')
        }).toFinishListeners()

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayProperty(delayAction.id, { source: 'person', key: 'expires_at' })
        }).toFinishListeners()

        expect(descriptionOf(delayAction.id)).toBe(customDescription)
    })
})
