import { customEventProperties } from './eventProperties'

describe('customEventProperties', () => {
    test('excludes system properties and preserves custom values in alphabetical order', () => {
        expect(
            customEventProperties({
                $current_url: 'https://example.com',
                $set: { email: 'demo@example.com' },
                distinct_id: 'person-1',
                token: 'fake-project-token',
                tags: ['design', 'review'],
                settings: { notifications: false },
                plan: 'pro',
                count: 0,
                enabled: false,
                empty: '',
                missing: null,
            })
        ).toEqual([
            ['count', '0'],
            ['empty', '""'],
            ['enabled', 'false'],
            ['missing', 'null'],
            ['plan', 'pro'],
            ['settings', '{\n  "notifications": false\n}'],
            ['tags', '[\n  "design",\n  "review"\n]'],
        ])
    })
})
