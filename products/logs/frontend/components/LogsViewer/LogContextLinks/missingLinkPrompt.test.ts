import { ParsedLogMessage } from 'products/logs/frontend/types'

import { MissingLink, buildMissingLinkPrompt } from './missingLinkPrompt'

const log = {
    uuid: 'log-1',
    timestamp: '2026-10-12T09:43:23.143Z',
    instrumentation_scope: '',
    resource_attributes: {
        'service.name': 'checkout-api',
        'telemetry.sdk.name': 'opentelemetry',
        'telemetry.sdk.language': 'nodejs',
    },
} as unknown as ParsedLogMessage

describe('buildMissingLinkPrompt', () => {
    test.each<[MissingLink[], string[], string[]]>([
        [['trace'], ['no trace ID', '2. Check that the active span context'], ['session and distinct IDs']],
        [
            ['session', 'person'],
            ['no session ID and distinct ID', '2. Check whether the frontend sends'],
            ['active span context'],
        ],
        [
            ['trace', 'session', 'person'],
            [
                'no trace ID, session ID and distinct ID',
                '2. Check that the active span',
                '3. Check whether the frontend',
            ],
            [],
        ],
    ])('for %j asks only about the missing IDs', (missing, included, excluded) => {
        const prompt = buildMissingLinkPrompt(log, missing)

        expect(prompt).toContain('"checkout-api"')
        expect(prompt).toContain('"opentelemetry nodejs"')
        for (const text of included) {
            expect(prompt).toContain(text)
        }
        for (const text of excluded) {
            expect(prompt).not.toContain(text)
        }
    })
})
