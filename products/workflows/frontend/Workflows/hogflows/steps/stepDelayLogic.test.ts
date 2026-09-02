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
    shouldAutoUpdateDescription,
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
    // An event property is `properties.x`, not `event.properties.x`: the expression is evaluated against
    // the same globals as a filter, where `event` is the event's name. Getting this wrong resolves to
    // nothing at run time and aborts the run instead of waiting.
    it.each([
        [{ source: 'person', key: 'expires_at' } as DelayProperty, 'person.properties.expires_at'],
        [{ source: 'event', key: 'scheduled_at' } as DelayProperty, 'properties.scheduled_at'],
        [{ source: 'person', key: '$trial_ends' } as DelayProperty, "person.properties['$trial_ends']"],
        [{ source: 'person', key: 'renews on' } as DelayProperty, "person.properties['renews on']"],
        [{ source: 'event', key: "o'clock" } as DelayProperty, "properties['o\\'clock']"],
    ])('%o round trips through %p', (property, expression) => {
        expect(buildDelayExpression(property)).toBe(expression)
        expect(parseDelayExpression(expression)).toEqual(property)
    })

    // Shown as a hand-written expression rather than a picked property, which is what invites the user to
    // re-pick it. Reading it back as a property would present an unrunnable step as configured.
    it.each([
        ['a composed expression', 'toDateTime(person.properties.a) + toIntervalDay(1)'],
        ['an event property written with the event prefix', 'event.properties.expires_at'],
    ])('reads back no property for %s', (_label, expression) => {
        expect(parseDelayExpression(expression)).toBeNull()
    })

    // The sign carries the direction. Losing it turns "a day before their trial ends" into a message
    // sent a day late, which reads as working right up until someone checks the send times.
    it.each([
        [{ duration: '1d', direction: 'before' } as DelayOffset, '-1d'],
        [{ duration: '2h', direction: 'after' } as DelayOffset, '2h'],
        [{ duration: '1.5d', direction: 'before' } as DelayOffset, '-1.5d'],
        [{ duration: '30s', direction: 'after' } as DelayOffset, '30s'],
    ])('%o round trips through %p', (offset, serialized) => {
        expect(buildDelayOffset(offset)).toBe(serialized)
        expect(parseDelayOffset(serialized)).toEqual(offset)
    })

    // 'on' has to save nothing rather than '0d', and a cleared duration input emits just its unit.
    it.each([
        [{ duration: '1d', direction: 'on' } as DelayOffset],
        [{ duration: 'd', direction: 'before' } as DelayOffset],
        [{ duration: '', direction: 'after' } as DelayOffset],
    ])('saves no offset for %o', (offset) => {
        expect(buildDelayOffset(offset)).toBeUndefined()
    })

    it('starts a fresh date delay on the date itself', () => {
        expect(parseDelayOffset(undefined).direction).toBe('on')
    })

    // Agent-created actions can omit description entirely, and editing such a delay must not throw.
    it('treats an action with no description as auto-written', () => {
        expect(shouldAutoUpdateDescription(undefined)).toBe(true)
    })

    // The API rejects a config carrying both modes, so a merge here would 400 every save. The value the
    // author set has to come back on a switch across and back all the same, which is why '5h' is not the
    // default: a default-valued fixture cannot tell a restored duration from a fresh one.
    it('drops the duration when switching to a date, and restores it when switching back', async () => {
        const delayAction = await setupInitialDelayAction(getDelayDescription({ delay_duration: '5h' }), {
            delay_duration: '5h',
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

        expect(configOf(delayAction.id)).toEqual({ delay_duration: '5h' })
    })

    // A misclick on the mode select must not throw away the date, its offset and its timezone.
    it('restores a configured date when switching to a duration and back', async () => {
        const configured = {
            delay_until: {
                expression: 'person.properties.expires_at',
                offset: '-2d',
                timezone: 'Europe/Berlin',
            },
        }
        const delayAction = await setupInitialDelayAction(getDelayDescription(configured), configured)

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayMode(delayAction.id, 'duration')
        }).toFinishListeners()
        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayMode(delayAction.id, 'until')
        }).toFinishListeners()

        expect(configOf(delayAction.id)).toEqual(configured)
    })

    it('composes the expression and offset onto delay_until', async () => {
        const delayAction = await setupInitialDelayAction('', { delay_until: { expression: '' } })

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayProperty(delayAction.id, { source: 'person', key: 'expires_at' })
        }).toFinishListeners()

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayOffset(delayAction.id, { duration: '1d', direction: 'before' })
        }).toFinishListeners()

        expect(configOf(delayAction.id)).toEqual({
            delay_until: { expression: 'person.properties.expires_at', offset: '-1d' },
        })
        expect(descriptionOf(delayAction.id)).toBe('Wait until 1 day before expires_at.')
    })

    // Clearing the amount emits a unit-only 'd', which serializes to no offset and reads back as
    // direction 'on', unmounting the amount field mid-edit. Keep the last offset so the author can
    // type a replacement; only picking 'on' actually drops it.
    it.each([
        ['keeps the last offset when the amount is cleared mid-edit', { duration: 'd', direction: 'before' }, '-2d'],
        ['drops the offset when the direction becomes on', { duration: '2d', direction: 'on' }, undefined],
    ])('%s', async (_label, offset, expected) => {
        const configured = { delay_until: { expression: 'person.properties.expires_at', offset: '-2d' } }
        const delayAction = await setupInitialDelayAction(getDelayDescription(configured), configured)

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayOffset(delayAction.id, offset as DelayOffset)
        }).toFinishListeners()

        expect(configOf(delayAction.id).delay_until?.offset).toBe(expected)
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

    it('should auto-update the description when the action has no description', async () => {
        // Agent-created actions can arrive without a description key; editing one must not throw on .trim().
        const delayAction = {
            id: `delay_action_${uuid()}`,
            type: 'delay',
            name: 'Delay',
            description: undefined as unknown as string,
            config: { delay_duration: '10m' },
            created_at: Date.now(),
            updated_at: Date.now(),
        } as HogFlowAction

        await expectLogic(wfLogic, () => {
            wfLogic.actions.setWorkflowInfo({
                actions: [...wfLogic.values.workflow.actions, delayAction],
            })
        }).toDispatchActions(['setWorkflowInfo'])

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
})
