import { z } from 'zod'

const configSchema = z.object({
    NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
    PORT: z.coerce.number().int().min(0).max(65535).default(4010),
    HOST: z.string().min(1).default('0.0.0.0'),
    LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),
    SHUTDOWN_GRACE_MS: z.coerce.number().int().positive().default(30000),
    DATABASE_URL: z.string().url().default('postgres://posthog:posthog@localhost:5432/posthog'),
})

export type ServiceConfig = z.infer<typeof configSchema>

export function loadConfig(environment: NodeJS.ProcessEnv = process.env): ServiceConfig {
    return configSchema.parse(environment)
}
