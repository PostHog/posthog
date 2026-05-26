import { z } from 'zod'

import { AGENT_DEV_DEFAULTS, devDefault } from '@posthog/agent-core'

const ConfigSchema = z.object({
    queueDbUrl: z.string().min(1),
    queueName: z.string().default('default'),
    posthogDbUrl: z.string().min(1),
    encryptionSaltKeys: z.string().min(1),
    redisUrl: z.string().optional(),
    kafkaBrokers: z.string().min(1),
    kafkaLogEntriesTopic: z.string().default('log_entries'),
    /**
     * Optional in the schema so the runner can boot under test substitutes
     * (e.g. `EchoExecutor`) without an Anthropic credential. `AssServerExecutor`
     * still reads `ANTHROPIC_API_KEY` from `process.env` directly at run time
     * and will fail there if missing — the bin can opt in to fail-fast at boot
     * by checking this field after `loadConfig()`.
     */
    anthropicApiKey: z.string().optional(),
    /** Max concurrent session jobs this worker process will hold. */
    concurrency: z.coerce.number().int().min(1).default(8),
})

export type RunnerConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): RunnerConfig {
    return ConfigSchema.parse({
        queueDbUrl: devDefault(env.AGENT_RUNTIME_QUEUE_DATABASE_URL, AGENT_DEV_DEFAULTS.agentRuntimeQueueDatabaseUrl),
        queueName: env.AGENT_RUNNER_QUEUE_NAME,
        posthogDbUrl: devDefault(env.POSTHOG_DATABASE_URL, AGENT_DEV_DEFAULTS.posthogDatabaseUrl),
        encryptionSaltKeys: devDefault(env.ENCRYPTION_SALT_KEYS, AGENT_DEV_DEFAULTS.encryptionSaltKeys),
        redisUrl: devDefault(env.REDIS_URL, AGENT_DEV_DEFAULTS.redisUrl),
        kafkaBrokers: devDefault(env.KAFKA_HOSTS, AGENT_DEV_DEFAULTS.kafkaHosts),
        kafkaLogEntriesTopic: env.KAFKA_LOG_ENTRIES_TOPIC,
        anthropicApiKey: env.ANTHROPIC_API_KEY,
        concurrency: env.AGENT_RUNNER_CONCURRENCY,
    })
}
