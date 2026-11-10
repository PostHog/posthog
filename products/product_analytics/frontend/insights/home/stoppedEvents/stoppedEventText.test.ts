import { dayjs } from 'lib/dayjs'

import {
    StoppedEventPayload,
    stoppedEventAnnotationText,
    stoppedEventLastCapture,
    stoppedEventLastSeen,
    stoppedEventPrompt,
} from './stoppedEventText'

const NOW = dayjs('2026-11-10T12:00:00Z')

const basePayload: StoppedEventPayload = {
    event: 'checkout_completed',
    event_definition_id: 'def-1',
    last_seen_at: '2026-11-05T09:00:00Z',
    insight_count: 3,
}

describe('stoppedEventText', () => {
    test.each([
        ['several days ago', basePayload, 'Last seen 5\u00a0days ago'],
        [
            'with the volume before',
            { ...basePayload, daily_average_before: 1240 },
            'Last seen 5\u00a0days ago, down from about 1.24K a day',
        ],
        ['under a day ago', { ...basePayload, last_seen_at: '2026-11-10T06:00:00Z' }, 'Last seen 1\u00a0day ago'],
    ])('last seen %s', (_name, payload, expected) => {
        expect(stoppedEventLastSeen(payload, NOW)).toEqual(expected)
    })

    test.each([
        ['nothing known', basePayload, null],
        ['only the SDK', { ...basePayload, last_lib: 'posthog-node' }, 'Last sent by posthog-node'],
        [
            'the SDK and page',
            { ...basePayload, last_lib: 'web', last_path: '/checkout/confirm' },
            'Last sent by web on /checkout/confirm',
        ],
    ])('last capture with %s', (_name, payload, expected) => {
        expect(stoppedEventLastCapture(payload)).toEqual(expected)
    })

    test.each([
        ['no annotation', basePayload, null],
        [
            'an annotation',
            { ...basePayload, annotation: { content: 'Released checkout v2', marked_at: '2026-11-05T08:00:00Z' } },
            'Possibly related: "Released checkout v2" on Nov 5',
        ],
    ])('annotation text with %s', (_name, payload, expected) => {
        expect(stoppedEventAnnotationText(payload)).toEqual(expected)
    })

    test.each([
        ['no context', basePayload, false],
        [
            'full context',
            {
                ...basePayload,
                daily_average_before: 1240,
                last_lib: 'web',
                last_path: '/checkout/confirm',
                annotation: { content: 'Released checkout v2', marked_at: '2026-11-05T08:00:00Z' },
            },
            true,
        ],
    ])('prompt with %s names the event and asks for a next step', (_name, payload, mentionsAnnotation) => {
        const prompt = stoppedEventPrompt(payload)
        expect(prompt).toContain('"checkout_completed"')
        expect(prompt).toContain('3\u00a0saved insights')
        expect(prompt).toContain('which insights to update or delete')
        expect(prompt.includes('Released checkout v2')).toBe(mentionsAnnotation)
        expect(prompt.includes('about 1240 times a day')).toBe(mentionsAnnotation)
        expect(prompt.includes('web SDK on /checkout/confirm')).toBe(mentionsAnnotation)
    })
})
