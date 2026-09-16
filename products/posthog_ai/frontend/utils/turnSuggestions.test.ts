import { buildScoutCreatePayload, parseTurnSuggestionParams } from './turnSuggestions'

const validParams = {
    turnIndex: 0,
    kind: 'scout',
    intent: 'metric_state',
    confidence: 0.9,
    title: 'Get this every week in Slack',
    description: 'A scout can rerun this count each week.',
    scout: {
        displayName: 'Weekly signups',
        description: 'Counts signed_up events for the last 7 days.',
        body: '# Weekly signups\n\nQuery signed_up for the last 7 days.',
        cadence: 'weekly',
    },
}

describe('turnSuggestions', () => {
    test.each([
        ['an unknown kind', { ...validParams, kind: 'dashboard' }],
        ['a notebook without a title', { ...validParams, kind: 'notebook', notebook: { title: ' ', summary: 'x' } }],
        ['a missing turn index', { ...validParams, turnIndex: undefined }],
        ['an empty scout prompt', { ...validParams, scout: { ...validParams.scout, body: '   ' } }],
        ['an unknown cadence', { ...validParams, scout: { ...validParams.scout, cadence: 'hourly' } }],
        ['a non-object frame', 'scout'],
    ])('parseTurnSuggestionParams drops a frame with %s', (_label, params) => {
        expect(parseTurnSuggestionParams(params)).toBeNull()
    })

    it('parseTurnSuggestionParams keeps the drafted scout and falls back on card copy', () => {
        expect(parseTurnSuggestionParams({ ...validParams, title: '', description: undefined })).toEqual({
            turnIndex: 0,
            kind: 'scout',
            intent: 'metric_state',
            confidence: 0.9,
            title: 'Turn this into a scout',
            description: 'Run this analysis on a schedule and post the results to Slack.',
            scout: validParams.scout,
        })
    })

    it('parseTurnSuggestionParams keeps a notebook suggestion with its drafted title', () => {
        expect(
            parseTurnSuggestionParams({
                turnIndex: 0,
                kind: 'notebook',
                intent: 'diagnostic',
                confidence: 0.8,
                title: 'Save this investigation to a notebook',
                description: 'Keep the queries and findings together.',
                notebook: { title: 'Why signups dropped on Tuesday', summary: 'A checkout error was the cause.' },
            })
        ).toEqual({
            turnIndex: 0,
            kind: 'notebook',
            intent: 'diagnostic',
            confidence: 0.8,
            title: 'Save this investigation to a notebook',
            description: 'Keep the queries and findings together.',
            notebook: { title: 'Why signups dropped on Tuesday', summary: 'A checkout error was the cause.' },
        })
    })

    it('buildScoutCreatePayload maps the cadence to a cron and the channel to a Slack destination', () => {
        const suggestion = parseTurnSuggestionParams(validParams)
        if (suggestion?.kind !== 'scout') {
            throw new Error('expected a scout suggestion')
        }

        expect(
            buildScoutCreatePayload({
                suggestion,
                cadence: 'daily',
                slackIntegrationId: 7,
                slackChannel: 'C123|#growth',
            })
        ).toEqual({
            display_name: 'Weekly signups',
            description: 'Counts signed_up events for the last 7 days.',
            body: validParams.scout.body,
            config: {
                run_cron_schedule: '0 9 * * *',
                output_destinations: { slack: { integration_id: 7, channel: 'C123|#growth' } },
            },
        })
    })
})
