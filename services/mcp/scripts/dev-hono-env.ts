type RuntimeEnvironment = Record<string, string | undefined>

const DEFAULT_FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'tasks-orchestration': true })

export function createDevHonoChildEnv(parentEnv: RuntimeEnvironment): RuntimeEnvironment {
    return {
        ...parentEnv,
        NODE_ENV: parentEnv.NODE_ENV ?? 'development',
        FEATURE_FLAG_OVERRIDES: parentEnv.FEATURE_FLAG_OVERRIDES ?? DEFAULT_FEATURE_FLAG_OVERRIDES,
        SHUTDOWN_PRESTOP_DELAY_MS: '0',
    }
}
