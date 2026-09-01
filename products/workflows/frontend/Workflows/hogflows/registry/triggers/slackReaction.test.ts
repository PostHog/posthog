import './slackReaction'

import { PropertyOperator } from '~/types'

import {
    SlackReactorMode,
    decodeSlackReactionFilters,
    encodeSlackReactionFilters,
    reactionName,
} from './slackReactionTriggerFilters'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('slack reaction trigger', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'slack-reaction')
        if (!triggerType) {
            throw new Error('Slack reaction trigger type not registered')
        }
        return triggerType
    }

    describe('filters round-trip', () => {
        it.each<{ name: string; mode: SlackReactorMode; ids: string[] }>([
            { name: 'anyone', mode: 'anyone', ids: [] },
            { name: 'specific people', mode: 'specific_people', ids: ['U01ABCDEF'] },
        ])('survives a save and reload for $name', ({ mode, ids }) => {
            // The editor reads its controls back out of the stored filters, so a mode that encodes
            // to something decode can't recognize silently resets the control on reopen.
            const filters = {
                channel: 'C0ALERTS',
                reactions: ['mag'],
                reactorMode: mode,
                reactorIds: ids,
                additional: [],
            }
            expect(decodeSlackReactionFilters(encodeSlackReactionFilters(filters))).toEqual(filters)
        })

        it('keeps filters the native controls do not own', () => {
            const custom = { key: 'item_user', value: ['U0BOT'], operator: PropertyOperator.Exact, type: 'event' }
            const encoded = encodeSlackReactionFilters({
                channel: 'C0ALERTS',
                reactions: ['mag'],
                reactorMode: 'anyone',
                reactorIds: [],
                additional: [custom],
            })

            expect(decodeSlackReactionFilters(encoded).additional).toEqual([custom])
        })
    })

    describe('emoji names', () => {
        it.each([
            ['already bare', 'mag', 'mag'],
            // People type what Slack shows them, but the event carries the bare name.
            ['typed with colons', ':mag:', 'mag'],
            ['carrying a skin tone', '+1::skin-tone-3', '+1'],
            ['padded with spaces', '  mag  ', 'mag'],
        ])('stores an emoji %s as the event spells it', (_name, typed, expected) => {
            expect(reactionName(typed)).toEqual(expected)
        })

        it('normalizes what a person typed before storing it', () => {
            const encoded = encodeSlackReactionFilters({
                channel: 'C0ALERTS',
                reactions: [':mag:'],
                reactorMode: 'anyone',
                reactorIds: [],
                additional: [],
            })

            expect(decodeSlackReactionFilters(encoded).reactions).toEqual(['mag'])
        })
    })

    describe('validation', () => {
        const validate = (
            overrides: Partial<Parameters<typeof encodeSlackReactionFilters>[0]>
        ): { valid: boolean; errors: Record<string, string> } | null =>
            getTriggerType().validate?.({
                type: 'slack-reaction',
                filters: {
                    properties: encodeSlackReactionFilters({
                        channel: 'C0ALERTS',
                        reactions: ['mag'],
                        reactorMode: 'anyone',
                        reactorIds: [],
                        additional: [],
                        ...overrides,
                    }),
                },
            } as any) ?? null

        it('accepts a channel and an emoji', () => {
            expect(validate({})).toEqual({ valid: true, errors: {} })
        })

        it('rejects a trigger with no channel', () => {
            expect(validate({ channel: null })?.valid).toBe(false)
        })

        it('rejects a trigger with no emoji', () => {
            // Without one, every reaction starts a run, including the :eyes: a run adds to the
            // message it is working on — so a replying workflow would retrigger itself.
            expect(validate({ reactions: [] })?.valid).toBe(false)
        })

        it('rejects specific people with nobody listed', () => {
            expect(validate({ reactorMode: 'specific_people', reactorIds: [] })?.valid).toBe(false)
        })
    })
})
