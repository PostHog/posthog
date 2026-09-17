import type { TurnSuggestion } from '../types/streamTypes'
import { BASE, INCIDENT_NOTEBOOK, INSIGHT, SCOUT, SUGGESTION_FRAMES } from './turnSuggestionFixtures'
import { parseTurnSuggestionParams } from './turnSuggestions'

describe('turnSuggestions', () => {
    test.each([
        ['an unknown kind', { ...SUGGESTION_FRAMES.scout, kind: 'dashboard' }],
        ['a notebook without a title', { ...SUGGESTION_FRAMES.notebook, notebook: { title: ' ', summary: 'x' } }],
        ['a missing turn index', { ...SUGGESTION_FRAMES.scout, turnIndex: undefined }],
        ['an empty scout prompt', { ...SUGGESTION_FRAMES.scout, scout: { ...SCOUT, body: '   ' } }],
        ['an unknown cadence', { ...SUGGESTION_FRAMES.scout, scout: { ...SCOUT, cadence: 'hourly' } }],
        [
            'an alert without an insight',
            { ...SUGGESTION_FRAMES.alert, alert: { direction: 'decrease', changePercent: 20 } },
        ],
        [
            'an alert with an unknown direction',
            { ...SUGGESTION_FRAMES.alert, alert: { ...INSIGHT, direction: 'either' } },
        ],
        [
            'an alert without a positive bound',
            { ...SUGGESTION_FRAMES.alert, alert: { ...INSIGHT, direction: 'decrease', changePercent: 0 } },
        ],
        ['a subscription without a cadence', { ...SUGGESTION_FRAMES.subscription, subscription: INSIGHT }],
        ['an error alert without an issue', { ...SUGGESTION_FRAMES.error_alert, errorAlert: { issueName: 'x' } }],
        ['a non-object frame', 'scout'],
    ])('parseTurnSuggestionParams drops a frame with %s', (_label, params) => {
        expect(parseTurnSuggestionParams(params)).toBeNull()
    })

    test.each<[TurnSuggestion['kind'], Record<string, unknown>]>([
        ['scout', { scout: SCOUT }],
        ['notebook', { notebook: INCIDENT_NOTEBOOK }],
        ['alert', { alert: { ...INSIGHT, direction: 'decrease', changePercent: 20 } }],
        ['subscription', { subscription: { ...INSIGHT, cadence: 'weekly' } }],
        ['error_alert', { errorAlert: { issueId: 'issue-1', issueName: 'Checkout error' } }],
    ])('parseTurnSuggestionParams keeps a %s frame with its draft', (kind, draft) => {
        expect(parseTurnSuggestionParams(SUGGESTION_FRAMES[kind])).toEqual({ ...BASE, kind, ...draft })
    })

    it('parseTurnSuggestionParams fills in the card copy and the scout mode, and needs a cause for an incident', () => {
        expect(
            parseTurnSuggestionParams({
                ...SUGGESTION_FRAMES.scout,
                title: '',
                description: undefined,
                scout: { ...SCOUT, mode: undefined },
            })
        ).toMatchObject({
            title: 'Turn this into a scout',
            description: 'Run this analysis on a schedule and post the results to Slack.',
            scout: { mode: 'report' },
        })
        expect(
            parseTurnSuggestionParams({
                ...SUGGESTION_FRAMES.notebook,
                notebook: { title: 'Why', summary: '', incident: { timeline: '- 14:10', cause: '', fix: '' } },
            })
        ).toMatchObject({ notebook: { incident: null } })
    })
})
