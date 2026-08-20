import './slack'

import { PropertyOperator } from '~/types'

import { SlackPosterMode, decodeSlackFilters, encodeSlackFilters } from './slackTriggerFilters'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('slack message trigger', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'slack-message')
        if (!triggerType) {
            throw new Error('Slack message trigger type not registered')
        }
        return triggerType
    }

    describe('filters round-trip', () => {
        it.each<{ name: string; mode: SlackPosterMode; ids: string[] }>([
            { name: 'anyone', mode: 'anyone', ids: [] },
            { name: 'people only', mode: 'people', ids: [] },
            { name: 'apps and bots only', mode: 'apps', ids: [] },
            { name: 'specific people', mode: 'specific_people', ids: ['U01ABCDEF'] },
            { name: 'specific apps', mode: 'specific_apps', ids: ['A01ABCDEF'] },
        ])('survives a save and reload for $name', ({ mode, ids }) => {
            // The editor reads its controls back out of the stored filters, so a mode that encodes
            // to something decode can't recognize silently resets the control on reopen.
            const filters = {
                channel: 'C0ALERTS',
                posterMode: mode,
                posterIds: ids,
                topLevelOnly: true,
                additional: [],
            }
            expect(decodeSlackFilters(encodeSlackFilters(filters))).toEqual(filters)
        })

        it('keeps filters the native controls do not own', () => {
            const custom = { key: 'text', value: ['fire'], operator: PropertyOperator.IContains, type: 'event' }
            const encoded = encodeSlackFilters({
                channel: 'C0ALERTS',
                posterMode: 'people',
                posterIds: [],
                topLevelOnly: false,
                additional: [custom],
            })

            expect(encoded).toContainEqual(custom)
            expect(decodeSlackFilters(encoded).additional).toEqual([custom])
        })

        it('reduces the picker composite to a channel id', () => {
            // The picker round-trips `C123|#name`; the event carries `C123`, so storing the
            // composite compiles a filter that matches nothing.
            const encoded = encodeSlackFilters({
                channel: 'C0ALERTS|#alerts',
                posterMode: 'anyone',
                posterIds: [],
                topLevelOnly: false,
                additional: [],
            })
            expect(decodeSlackFilters(encoded).channel).toBe('C0ALERTS')
        })

        it('separates top-level posts on thread_ts, not the boolean', () => {
            // is_thread_reply is a real boolean on the event, and comparing it against a string
            // would never match. Absence of thread_ts is what marks a top-level post.
            const encoded = encodeSlackFilters({
                channel: null,
                posterMode: 'anyone',
                posterIds: [],
                topLevelOnly: true,
                additional: [],
            })
            expect(encoded).toContainEqual(
                expect.objectContaining({ key: 'thread_ts', operator: PropertyOperator.IsNotSet })
            )
        })

        it.each<SlackPosterMode>(['specific_people', 'specific_apps'])(
            'keeps %s selected before any id is typed',
            (mode) => {
                // The control re-derives from the stored filters on every render, so a mode that
                // encodes to nothing snaps straight back to "anyone" the moment you pick it.
                const encoded = encodeSlackFilters({
                    channel: null,
                    posterMode: mode,
                    posterIds: [],
                    topLevelOnly: false,
                    additional: [],
                })
                expect(decodeSlackFilters(encoded).posterMode).toBe(mode)
            }
        )
    })

    describe('registry entry', () => {
        it.each([
            { name: 'no channel filter', properties: [], valid: false },
            { name: 'channel filter present', properties: [{ key: 'channel', value: ['C0ALERTS'] }], valid: true },
            { name: 'other filters alone', properties: [{ key: 'text', value: ['fire'] }], valid: false },
        ])('validate returns valid=$valid for $name', ({ properties, valid }) => {
            const result = getTriggerType().validate!({ type: 'slack-message', filters: { properties } } as any)
            expect(result?.valid).toBe(valid)
        })

        it('validate returns null for a non slack-message config', () => {
            expect(getTriggerType().validate!({ type: 'event', filters: {} } as any)).toBeNull()
        })

        it('is gated behind the slack-workflow-triggers feature flag', () => {
            expect(getTriggerType().featureFlag).toBe('slack-workflow-triggers')
        })

        it('buildConfig produces a config recognized by matchConfig', () => {
            const triggerType = getTriggerType()
            const config = triggerType.buildConfig()
            expect(config.type).toBe('slack-message')
            expect(triggerType.matchConfig!(config)).toBe(true)
        })

        it('defaults to people only so a workflow cannot retrigger on its own message', () => {
            expect(decodeSlackFilters(getTriggerType().buildConfig().filters.properties).posterMode).toBe('people')
        })
    })
})
