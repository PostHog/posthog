import { env as _cfEnv } from 'cloudflare:workers'

export const env = new Proxy({} as Record<string, string | undefined>, {
    get: (_, key: string) => (_cfEnv as any)?.[key] ?? process.env[key],
})
