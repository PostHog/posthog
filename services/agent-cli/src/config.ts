/**
 * CLI configuration — resolved from environment variables, with automatic
 * local dev detection.
 *
 * When running inside a PostHog repo clone, defaults to localhost + the
 * well-known dev API key so there's zero config needed for local development.
 *
 * Otherwise falls back to env vars compatible with the existing posthog-cli
 * conventions (POSTHOG_CLI_API_KEY, POSTHOG_CLI_PROJECT_ID, POSTHOG_CLI_HOST).
 */

import * as fs from 'node:fs'
import * as path from 'node:path'

export interface CliConfig {
    apiKey: string
    projectId: string
    host: string
}

const LOCAL_DEV_DEFAULTS = {
    host: 'http://localhost:8010',
    apiKey: 'phx_dev_local_test_api_key_1234567890abcdef',
    projectId: '1',
}

function isPostHogRepo(): boolean {
    // Walk up from cwd looking for posthog/settings/ — the Django settings dir
    // that only exists in the PostHog repo.
    let dir = process.cwd()
    for (let i = 0; i < 10; i++) {
        if (fs.existsSync(path.join(dir, 'posthog', 'settings', 'web.py'))) {
            return true
        }
        const parent = path.dirname(dir)
        if (parent === dir) {
            break
        }
        dir = parent
    }
    return false
}

function envOrDefault(names: string[], fallback: string | undefined, description: string): string {
    for (const name of names) {
        const value = process.env[name]
        if (value) {
            return value
        }
    }
    if (fallback !== undefined) {
        return fallback
    }
    throw new Error(`Missing ${description}. Set one of: ${names.join(', ')}`)
}

export function resolveConfig(): CliConfig {
    const localDev = isPostHogRepo()
    const defaults = localDev ? LOCAL_DEV_DEFAULTS : undefined

    return {
        apiKey: envOrDefault(
            ['POSTHOG_API_KEY', 'POSTHOG_CLI_API_KEY', 'POSTHOG_CLI_TOKEN'],
            defaults?.apiKey,
            'API key'
        ),
        projectId: envOrDefault(
            ['POSTHOG_PROJECT_ID', 'POSTHOG_CLI_PROJECT_ID', 'POSTHOG_CLI_ENV_ID'],
            defaults?.projectId,
            'project ID'
        ),
        host: envOrDefault(['POSTHOG_HOST', 'POSTHOG_CLI_HOST'], defaults?.host ?? 'https://us.posthog.com', 'host'),
    }
}
