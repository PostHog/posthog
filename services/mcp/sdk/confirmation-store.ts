import type { PayloadStashRedis } from '@/lib/signed-state'

/** Confirmation state belongs to one SDK client and expires with its signed tokens. */
export class ConfirmationStore implements PayloadStashRedis {
    private readonly entries = new Map<string, { value: string; expires: number }>()

    private read(key: string): { value: string; expires: number } | undefined {
        const now = Date.now()
        for (const [name, entry] of this.entries) {
            if (entry.expires <= now) {
                this.entries.delete(name)
            }
        }
        return this.entries.get(key)
    }

    async get(key: string): Promise<string | null> {
        return this.read(key)?.value ?? null
    }

    async set(key: string, value: string, ...args: (string | number)[]): Promise<string | null> {
        if (args.includes('NX') && this.read(key)) {
            return null
        }
        const ex = args.indexOf('EX')
        const expires = ex >= 0 ? Date.now() + Number(args[ex + 1]) * 1000 : Infinity
        this.entries.set(key, { value, expires })
        return 'OK'
    }

    async del(...keys: string[]): Promise<number> {
        return keys.reduce((count, key) => count + Number(this.entries.delete(key)), 0)
    }

    async incrby(key: string, increment: number): Promise<number> {
        const entry = this.read(key)
        const value = Number(entry?.value ?? 0) + increment
        this.entries.set(key, { value: String(value), expires: entry?.expires ?? Infinity })
        return value
    }

    async expire(key: string, seconds: number): Promise<number> {
        const entry = this.read(key)
        if (!entry) {
            return 0
        }
        entry.expires = Date.now() + seconds * 1000
        return 1
    }

    async ttl(key: string): Promise<number> {
        const entry = this.read(key)
        return entry ? (entry.expires === Infinity ? -1 : Math.ceil((entry.expires - Date.now()) / 1000)) : -2
    }
}
