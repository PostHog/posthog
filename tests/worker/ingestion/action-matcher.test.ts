import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import { DateTime } from 'luxon'

import {
    Action,
    ActionStep,
    ActionStepUrlMatching,
    Element,
    Hub,
    PropertyOperator,
    RawAction,
} from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { commonUserId } from '../../helpers/plugins'
import { insertRow, resetTestDatabase } from '../../helpers/sql'

describe('ActionMatcher', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let actionMatcher: ActionMatcher
    let actionCounter: number

    beforeEach(async () => {
        await resetTestDatabase(undefined, undefined, undefined, { withExtendedTestData: false })
        ;[hub, closeServer] = await createHub()
        actionMatcher = hub.actionMatcher
        actionCounter = 0
    })

    afterEach(async () => {
        await closeServer()
    })

    /** Return a test action created on a common base using provided steps. */
    async function createTestAction(partialSteps: Partial<ActionStep>[]): Promise<Action> {
        const action: RawAction = {
            id: actionCounter++,
            team_id: 2,
            name: 'Test',
            created_at: new Date().toISOString(),
            created_by_id: commonUserId,
            deleted: false,
            post_to_slack: false,
            slack_message_format: '',
            is_calculating: false,
            updated_at: new Date().toISOString(),
            last_calculated_at: new Date().toISOString(),
        }
        const steps: ActionStep[] = partialSteps.map(
            (partialStep, index) =>
                ({
                    id: action.id * 100 + index,
                    action_id: action.id,
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    name: null,
                    event: null,
                    properties: null,
                    ...partialStep,
                } as ActionStep)
        )
        await insertRow(hub.db.postgres, 'posthog_action', action)
        await Promise.all(steps.map((step) => insertRow(hub.db.postgres, 'posthog_actionstep', step)))
        await hub.actionManager.reloadAction(action.team_id, action.id)
        return { ...action, steps }
    }

    /** Return a test event created on a common base using provided property overrides. */
    function createTestEvent(overrides: Partial<PluginEvent> = {}): PluginEvent {
        const url: string = overrides.properties?.$current_url ?? 'http://example.com/foo/'
        return {
            distinct_id: 'my_id',
            ip: '127.0.0.1',
            site_url: url,
            team_id: 2,
            now: new Date().toISOString(),
            event: '$pageview',
            properties: { $current_url: url },
            ...overrides,
        }
    }

    describe('#match()', () => {
        it('returns no match if action has no steps', async () => {
            await createTestAction([])

            const event: PluginEvent = createTestEvent()

            expect(await actionMatcher.match(event)).toEqual([])
        })

        it('returns a match in case of property operator exact', async () => {
            const actionDefinitionOpExact: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 'bar', operator: 'exact' as PropertyOperator }],
                },
            ])
            const actionDefinitionOpUndefined: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 'bar' }], // undefined operator should mean "exact"
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of property operator is not', async () => {
            const actionDefinitionOpIsNot: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 'bar', operator: 'is_not' as PropertyOperator }],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpIsNot])
        })

        it('returns a match in case of property operator contains', async () => {
            const actionDefinitionOpContains: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: 'bar', operator: 'icontains' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of property operator does not contain', async () => {
            const actionDefinitionOpNotContains: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: 'bar', operator: 'not_icontains' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpNotContains])
        })

        it('returns a match in case of property operator regex', async () => {
            const actionDefinitionOpRegex1: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: '^bar', operator: 'regex' as PropertyOperator }],
                },
            ])
            const actionDefinitionOpRegex2: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: '(?:.+bar|[A-Z])', operator: 'regex' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpRegex1])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpRegex1])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpRegex2])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([
                actionDefinitionOpRegex1,
                actionDefinitionOpRegex2,
            ])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpRegex2])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of property operator not regex', async () => {
            const actionDefinitionOpNotRegex1: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: '^bar', operator: 'not_regex' as PropertyOperator },
                    ],
                },
            ])
            const actionDefinitionOpNotRegex2: Action = await createTestAction([
                {
                    properties: [
                        {
                            type: 'event',
                            key: 'foo',
                            value: '(?:.+bar|[A-Z])',
                            operator: 'not_regex' as PropertyOperator,
                        },
                    ],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpNotRegex2])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpNotRegex2])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpNotRegex1])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpNotRegex1])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFooNull)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
        })

        it('returns a match in case of property operator is set', async () => {
            const actionDefinitionOpIsSet: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', operator: 'is_set' as PropertyOperator }],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpIsSet])
        })

        it('returns a match in case of property operator is not set', async () => {
            const actionDefinitionOpIsNotSet: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', operator: 'is_not_set' as PropertyOperator }],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber: PluginEvent = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([actionDefinitionOpIsNotSet])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([actionDefinitionOpIsNotSet])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of property operator greater than', async () => {
            const actionDefinitionOpGreaterThan: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 5, operator: 'gt' as PropertyOperator }],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumberMinusOne: PluginEvent = createTestEvent({ properties: { foo: -1 } })
            const eventFooNumberFive: PluginEvent = createTestEvent({ properties: { foo: 5 } })
            const eventFooNumberSevenNines: PluginEvent = createTestEvent({ properties: { foo: 9999999 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberMinusOne)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberFive)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberSevenNines)).toEqual([actionDefinitionOpGreaterThan])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of property operator less than', async () => {
            const actionDefinitionOpLessThan: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 5, operator: 'lt' as PropertyOperator }],
                },
            ])

            const eventFooBar: PluginEvent = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot: PluginEvent = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR: PluginEvent = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz: PluginEvent = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara: PluginEvent = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar: PluginEvent = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumberMinusOne: PluginEvent = createTestEvent({ properties: { foo: -1 } })
            const eventFooNumberFive: PluginEvent = createTestEvent({ properties: { foo: 5 } })
            const eventFooNumberSevenNines: PluginEvent = createTestEvent({ properties: { foo: 9999999 } })
            const eventNoNothing: PluginEvent = createTestEvent()
            const eventFigNumber: PluginEvent = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue: PluginEvent = createTestEvent({ properties: { foo: true } })
            const eventFooNull: PluginEvent = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberMinusOne)).toEqual([actionDefinitionOpLessThan])
            expect(await actionMatcher.match(eventFooNumberFive)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberSevenNines)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpLessThan]) // true is a 1
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of URL contains page view', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: 'example.com',
                    url_matching: ActionStepUrlMatching.Contains,
                    event: '$pageview',
                },
            ])
            const actionDefinitionEmptyMatching: Action = await createTestAction([
                {
                    url: 'example.com',
                    url_matching: '' as ActionStepUrlMatching, // Empty url_matching should mean "contains"
                    event: '$pageview',
                },
            ])

            const eventPosthog: PluginEvent = createTestEvent({
                properties: { $current_url: 'http://posthog.com/pricing' },
            })
            const eventExample: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/' },
            })

            expect(await actionMatcher.match(eventPosthog)).toEqual([])
            expect(await actionMatcher.match(eventExample)).toEqual([actionDefinition, actionDefinitionEmptyMatching])
        })

        it('returns a match in case of URL contains page views with % and _', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: 'exampl_.com/%.html',
                    url_matching: ActionStepUrlMatching.Contains,
                    event: '$pageview',
                },
            ])
            const actionDefinitionEmptyMatching: Action = await createTestAction([
                {
                    url: 'exampl_.com/%.html',
                    url_matching: '' as ActionStepUrlMatching, // Empty url_matching should mean "contains"
                    event: '$pageview',
                },
            ])

            const eventExample: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/' },
            })
            const eventExampleHtml: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/index.html' },
            })

            expect(await actionMatcher.match(eventExample)).toEqual([])
            expect(await actionMatcher.match(eventExampleHtml)).toEqual([
                actionDefinition,
                actionDefinitionEmptyMatching,
            ])
        })

        it('returns a match in case of URL matches regex page views', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: String.raw`^https?:\/\/example\.com\/\d+(\/[a-r]*\/?)?$`,
                    url_matching: ActionStepUrlMatching.Regex,
                    event: '$pageview',
                },
            ])

            const eventExampleOk1: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/23/hello' },
            })
            const eventExampleOk2: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/3/abc/' },
            })
            const eventExampleBad1: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/3/xyz/' },
            })
            const eventExampleBad2: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/' },
            })
            const eventExampleBad3: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/uno/dos/' },
            })
            const eventExampleBad4: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://example.com/1foo/' },
            })

            expect(await actionMatcher.match(eventExampleOk1)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleOk2)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad3)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad4)).toEqual([])
        })

        it('returns a match in case of URL matches exactly page views', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: 'https://www.mozilla.org/de/',
                    url_matching: ActionStepUrlMatching.Exact,
                    event: '$pageview',
                },
            ])

            const eventExampleOk: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://www.mozilla.org/de/' },
            })
            const eventExampleBad1: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://www.mozilla.org/de' },
            })
            const eventExampleBad2: PluginEvent = createTestEvent({
                properties: { $current_url: 'https://www.mozilla.org/de/firefox/' },
            })

            expect(await actionMatcher.match(eventExampleOk)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
        })

        it('returns a match in case of exact event name', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    event: 'meow',
                },
            ])

            const eventExampleOk: PluginEvent = createTestEvent({
                event: 'meow',
            })
            const eventExampleBad1: PluginEvent = createTestEvent({
                event: '$meow',
            })
            const eventExampleBad2: PluginEvent = createTestEvent({
                event: 'WOOF',
            })

            expect(await actionMatcher.match(eventExampleOk)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
        })

        it('returns a match in case of exact event name AND URL contains', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    event: 'meow',
                    url_matching: ActionStepUrlMatching.Contains,
                    url: 'pets.com/',
                },
            ])

            const eventExampleOk1: PluginEvent = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'http://www.pets.com/' },
            })
            const eventExampleOk2: PluginEvent = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'https://pets.com/food' },
            })
            const eventExampleBad1: PluginEvent = createTestEvent({
                event: '$meow',
                properties: { $current_url: 'https://xyz.pets.com/' },
            })
            const eventExampleBad2: PluginEvent = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'https://www.pets.com.de/' },
            })
            const eventExampleBad3: PluginEvent = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'https://www.pets.co' },
            })

            expect(await actionMatcher.match(eventExampleOk1)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleOk2)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad3)).toEqual([])
        })

        it('returns a match in case of cohort match', async () => {
            const testCohort = await hub.db.createCohort({ name: 'Test', created_by_id: commonUserId, team_id: 2 })

            const actionDefinition: Action = await createTestAction([
                {
                    properties: [{ type: 'cohort', key: 'id', value: testCohort.id }],
                },
            ])

            const randomPerson = await hub.db.createPerson(
                DateTime.local(),
                {},
                actionDefinition.team_id,
                null,
                true,
                new UUIDT().toString(),
                ['random']
            )
            const cohortPerson = await hub.db.createPerson(
                DateTime.local(),
                {},
                actionDefinition.team_id,
                null,
                true,
                new UUIDT().toString(),
                ['cohort']
            )
            await hub.db.addPersonToCohort(testCohort.id, cohortPerson.id)

            const eventExamplePersonBad: PluginEvent = createTestEvent({
                event: 'meow',
                distinct_id: 'random',
            })
            const eventExamplePersonOk: PluginEvent = createTestEvent({
                event: 'meow',
                distinct_id: 'cohort',
            })
            const eventExamplePersonUnknown: PluginEvent = createTestEvent({
                event: 'meow',
                distinct_id: 'unknown',
            })

            expect(
                await actionMatcher.match(
                    eventExamplePersonOk,
                    await hub.db.fetchPerson(actionDefinition.team_id, eventExamplePersonOk.distinct_id)
                )
            ).toEqual([actionDefinition])
            expect(
                await actionMatcher.match(
                    eventExamplePersonBad,
                    await hub.db.fetchPerson(actionDefinition.team_id, eventExamplePersonBad.distinct_id)
                )
            ).toEqual([])
            expect(
                await actionMatcher.match(
                    eventExamplePersonUnknown,
                    await hub.db.fetchPerson(actionDefinition.team_id, eventExamplePersonUnknown.distinct_id)
                )
            ).toEqual([])
        })
    })

    describe('#checkElementsAgainstSelector()', () => {
        it('handles any descendant selector', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main .headline')).toBeTruthy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'h1 div')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, '.top main')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main div')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main .top')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div .headline')).toBeTruthy()
        })

        it('handles direct descendant selector', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > h1')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .headline')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .top > h1')).toBeTruthy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'h1 > div')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, '.top > main')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > div')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .top')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div > h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div > .headline')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 1', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['inner'] },
                { tag_name: 'div', attr_class: ['outer'] },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > h1')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .inner')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .outer > .inner > h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .inner > h1')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .outer > h1')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'h1 > div')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'outer > main')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > div')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .outer')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div > h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, '.inner > .headline')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 2', () => {
            const elements: Element[] = [
                { tag_name: 'span' },
                { tag_name: 'div' },
                { tag_name: 'a' },
                { tag_name: 'div' },
                { tag_name: 'div' },
                { tag_name: 'aside' },
                { tag_name: 'section' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'aside div > span')).toBeTruthy()
        })
    })
})
