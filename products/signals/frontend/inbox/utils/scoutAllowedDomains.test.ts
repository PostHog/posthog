import {
    MAX_SCOUT_ALLOWED_DOMAINS,
    normalizeScoutDomain,
    parseScoutAllowedDomainsInput,
    withScoutDomainsAdded,
} from './scoutAllowedDomains'

describe('scoutAllowedDomains', () => {
    // Each rejection here is one the sandbox would also reject at provisioning time, where the
    // scout is already running unattended. Letting one through turns a typo into a failed run.
    it.each([
        ['plain host', 'status.example.com', 'status.example.com'],
        ['upper case and padding', '  Status.Example.COM ', 'status.example.com'],
        ['leftmost wildcard', '*.Example.com', '*.example.com'],
        ['rooted name', 'example.com.', 'example.com'],
        ['scheme', 'https://example.com', null],
        ['path', 'example.com/status', null],
        ['port', 'example.com:8443', null],
        ['ipv4 address', '10.0.0.1', null],
        ['localhost', 'localhost', null],
        ['docker host alias', 'host.docker.internal', null],
        ['single label', 'example', null],
        ['interior wildcard', 'api.*.example.com', null],
        ['bare wildcard', '*', null],
        ['leading hyphen label', '-example.com', null],
        ['empty', '   ', null],
    ])('normalizes %s', (_name, input, expected) => {
        expect(normalizeScoutDomain(input)).toBe(expected)
    })

    it('splits a pasted list on commas and whitespace and reports what it could not use', () => {
        const parsed = parseScoutAllowedDomainsInput('status.example.com, *.example.org\nnot a domain')

        expect(parsed.domains).toEqual(['status.example.com', '*.example.org'])
        expect(parsed.invalid).toEqual(['not', 'a', 'domain'])
    })

    it('keeps insertion order, drops repeats, and refuses to go over the cap', () => {
        expect(withScoutDomainsAdded(['b.example.com'], ['a.example.com', 'b.example.com'])).toEqual({
            domains: ['b.example.com', 'a.example.com'],
            overCap: false,
        })
        expect(withScoutDomainsAdded(['a.example.com'], ['a.example.com'])).toEqual({
            domains: null,
            overCap: false,
        })

        const atCap = Array.from({ length: MAX_SCOUT_ALLOWED_DOMAINS }, (_, index) => `host-${index}.example.com`)
        expect(withScoutDomainsAdded(atCap, ['one-too-many.example.com'])).toEqual({
            domains: null,
            overCap: true,
        })
    })
})
