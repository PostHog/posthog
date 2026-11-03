import { defaultCloudRegion, type RegionId, validateHost } from './regions'

describe('defaultCloudRegion', () => {
    it.each<[string | null, string | null, RegionId | undefined, 'us' | 'eu']>([
        ['DE', 'Europe/Berlin', undefined, 'eu'],
        ['GB', 'Europe/London', undefined, 'eu'],
        ['CY', 'Asia/Nicosia', undefined, 'eu'],
        ['fi', null, undefined, 'eu'],
        ['US', 'America/New_York', undefined, 'us'],
        ['AU', 'Australia/Sydney', undefined, 'us'],
        [null, 'Europe/Paris', undefined, 'eu'],
        [null, null, undefined, 'us'],
        ['DE', 'Europe/Berlin', 'us', 'us'],
        ['US', 'America/New_York', 'eu', 'eu'],
        ['DE', 'Europe/Berlin', 'custom', 'eu'],
    ])('device region %s, timezone %s and saved region %s select %s', (regionCode, timeZone, saved, expected) => {
        expect(defaultCloudRegion(regionCode, timeZone, saved)).toBe(expected)
    })
})

describe('regions', () => {
    const originalUsClientId = process.env.EXPO_PUBLIC_OAUTH_US_CLIENT_ID
    const originalEuClientId = process.env.EXPO_PUBLIC_OAUTH_EU_CLIENT_ID

    afterEach(() => {
        if (originalUsClientId === undefined) {
            delete process.env.EXPO_PUBLIC_OAUTH_US_CLIENT_ID
        } else {
            process.env.EXPO_PUBLIC_OAUTH_US_CLIENT_ID = originalUsClientId
        }
        if (originalEuClientId === undefined) {
            delete process.env.EXPO_PUBLIC_OAUTH_EU_CLIENT_ID
        } else {
            process.env.EXPO_PUBLIC_OAUTH_EU_CLIENT_ID = originalEuClientId
        }
        jest.dontMock('@/lib/environment')
    })

    test.each(['production', 'development', 'preview'] as const)(
        '%s builds select the matching cloud OAuth registration',
        (variant) => {
            jest.isolateModules(() => {
                jest.doMock('@/lib/environment', () => ({
                    ...jest.requireActual('@/lib/environment'),
                    buildVariant: variant,
                }))
                process.env.EXPO_PUBLIC_OAUTH_US_CLIENT_ID = 'internal-us-client'
                process.env.EXPO_PUBLIC_OAUTH_EU_CLIENT_ID = 'internal-eu-client'
                const { CLOUD_REGIONS } = jest.requireActual<typeof import('./regions')>('./regions')
                expect(CLOUD_REGIONS.map((region) => region.clientId)).toEqual(
                    variant === 'production'
                        ? ['a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm', '1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU']
                        : ['internal-us-client', 'internal-eu-client']
                )
            })
        }
    )

    test('an unconfigured internal build has no production cloud client fallback', () => {
        jest.isolateModules(() => {
            jest.doMock('@/lib/environment', () => ({
                ...jest.requireActual('@/lib/environment'),
                buildVariant: 'preview',
            }))
            delete process.env.EXPO_PUBLIC_OAUTH_US_CLIENT_ID
            delete process.env.EXPO_PUBLIC_OAUTH_EU_CLIENT_ID
            const { CLOUD_REGIONS } = jest.requireActual<typeof import('./regions')>('./regions')
            expect(CLOUD_REGIONS.map((region) => region.clientId)).toEqual(['', ''])
        })
    })

    test.each([
        ['us.posthog.com', 'https://us.posthog.com'],
        ['https://posthog.example.com/project/2/', 'https://posthog.example.com'],
        ['http://localhost:8010', 'http://localhost:8010'],
        ['http://127.0.0.1:8000', 'http://127.0.0.1:8000'],
        ['http://[::1]:8010', 'http://[::1]:8010'],
        ['http://[0:0:0:0:0:0:0:1]:8010', 'http://[::1]:8010'],
    ])('accepts %s as %s', (input, host) => {
        expect(validateHost(input)).toEqual({ ok: true, host })
    })

    test.each([
        ['an empty value', '  '],
        ['plain http to a remote host', 'http://posthog.example.com'],
        ['another loopback address outside the native allowlist', 'http://127.0.0.2:8010'],
        ['the emulator host alias', 'http://10.0.2.2:8010'],
        ['a localhost subdomain', 'http://app.localhost:8010'],
        ['an IPv4-mapped IPv6 address', 'http://[::ffff:127.0.0.1]:8010'],
        ['a non-web scheme', 'ftp://posthog.example.com'],
        ['a script URL', 'javascript:alert(1)'],
    ])('rejects %s', (_name, input) => {
        expect(validateHost(input)).toMatchObject({ ok: false })
    })

    test.each([
        ['http://localhost:8010', false],
        ['http://127.0.0.1:8000', false],
        ['http://[::1]:8010', false],
        ['https://localhost:8010', true],
    ])('a store build given %s accepts it: %s', (input, ok) => {
        expect(validateHost(input, false)).toMatchObject({ ok })
    })
})
