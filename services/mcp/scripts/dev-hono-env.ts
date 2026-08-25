type RuntimeEnvironment = Record<string, string | undefined>

export function createDevHonoChildEnv(parentEnv: RuntimeEnvironment): RuntimeEnvironment {
    return {
        ...parentEnv,
        NODE_ENV: parentEnv.NODE_ENV ?? 'development',
        SHUTDOWN_PRESTOP_DELAY_MS: '0',
    }
}
