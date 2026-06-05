export const EXPERIMENTAL_API_ENV = 'POSTHOG_CLI_EXPERIMENTAL_API'

const ENABLED_VALUES = new Set(['1', 'true', 'yes', 'on'])

export function isExperimentalApiEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
    const value = env[EXPERIMENTAL_API_ENV]
    return value ? ENABLED_VALUES.has(value.toLowerCase()) : false
}

export function requireExperimentalApiEnabled(opts: { flagEnabled?: boolean; env?: NodeJS.ProcessEnv } = {}): void {
    if (opts.flagEnabled || isExperimentalApiEnabled(opts.env)) {
        return
    }

    throw new Error(
        `The \`posthog-cli api\` command group is experimental. Set ${EXPERIMENTAL_API_ENV}=1 or pass --experimental to use it.`
    )
}
