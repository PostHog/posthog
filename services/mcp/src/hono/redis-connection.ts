import type Redis from 'ioredis'

export async function connectRedis(redis: InstanceType<typeof Redis>, timeoutMs: number = 45_000): Promise<void> {
    await new Promise<void>((resolve, reject) => {
        let timer: ReturnType<typeof setTimeout>

        function cleanup(): void {
            clearTimeout(timer)
            redis.removeListener('ready', onReady)
            redis.removeListener('end', onEnd)
        }

        function onReady(): void {
            cleanup()
            resolve()
        }

        function onEnd(): void {
            cleanup()
            reject(new Error('Redis connection ended before startup'))
        }

        timer = setTimeout(() => {
            cleanup()
            redis.disconnect()
            reject(new Error(`Redis did not become ready within ${timeoutMs}ms`))
        }, timeoutMs)

        redis.once('ready', onReady)
        redis.once('end', onEnd)
        // connect() rejects on the first socket close while ioredis continues reconnecting.
        void redis.connect().catch(() => {})
    })
}
