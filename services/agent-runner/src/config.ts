import { z } from 'zod'

const ConfigSchema = z.object({
    /** agent-runtime queue DB (where session jobs live). */
    queueDbUrl: z.string().min(1),
    queueName: z.string().default('default'),
    /** Main posthog Postgres — for reading agent_stack_* rows + decrypting secrets. */
    posthogDbUrl: z.string().min(1),
    /**
     * Same comma-separated key list Django uses for `EncryptedTextField`. The runner is
     * the only process that decrypts; ingress never touches secrets.
     */
    encryptionSaltKeys: z.string().min(1),
    redisUrl: z.string().optional(),
    /** Anthropic API key — wired into the real SDK executor once it lands. */
    anthropicApiKey: z.string().optional(),
})

export type RunnerConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): RunnerConfig {
    return ConfigSchema.parse({
        queueDbUrl: env.AGENT_RUNTIME_QUEUE_DATABASE_URL,
        queueName: env.AGENT_RUNNER_QUEUE_NAME,
        posthogDbUrl: env.POSTHOG_DATABASE_URL,
        encryptionSaltKeys: env.ENCRYPTION_SALT_KEYS,
        redisUrl: env.REDIS_URL,
        anthropicApiKey: env.ANTHROPIC_API_KEY,
    })
}
