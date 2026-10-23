import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { resolveCliConfig } from '@/cli/config'

describe('resolveCliConfig host', () => {
    const saved = { POSTHOG_HOST: process.env.POSTHOG_HOST, POSTHOG_CLI_HOST: process.env.POSTHOG_CLI_HOST }

    beforeEach(() => {
        delete process.env.POSTHOG_HOST
        delete process.env.POSTHOG_CLI_HOST
    })

    afterEach(() => {
        for (const [name, value] of Object.entries(saved)) {
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        }
    })

    it.each([
        ['POSTHOG_CLI_HOST', 'us.posthog.com', 'https://us.posthog.com'],
        ['POSTHOG_HOST', 'eu.posthog.com/', 'https://eu.posthog.com'],
        ['POSTHOG_HOST', 'http://localhost:8010', 'http://localhost:8010'],
        ['POSTHOG_CLI_HOST', 'https://us.posthog.com', 'https://us.posthog.com'],
    ])('normalizes %s=%s to %s', (name, value, expected) => {
        process.env[name] = value
        expect(resolveCliConfig().host).toBe(expected)
    })

    it.each([
        ['POSTHOG_CLI_HOST', 'us posthog com'],
        ['POSTHOG_HOST', 'ftp://us.posthog.com'],
    ])('rejects %s=%s with an error that names the env var', (name, value) => {
        process.env[name] = value
        expect(() => resolveCliConfig()).toThrow(name)
    })
})
