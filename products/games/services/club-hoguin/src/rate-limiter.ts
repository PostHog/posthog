// A token bucket for each key. A key that sends requests faster than the rate, after its burst, gets refused.
export class RateLimiter {
    private readonly ratePerSecond: number
    private readonly burst: number
    private readonly buckets = new Map<string, { tokens: number; at: number }>()

    constructor(ratePerSecond: number, burst: number) {
        this.ratePerSecond = ratePerSecond
        this.burst = burst
    }

    allow(key: string, now: number): boolean {
        const bucket = this.buckets.get(key) ?? { tokens: this.burst, at: now }
        bucket.tokens = Math.min(this.burst, bucket.tokens + ((now - bucket.at) / 1000) * this.ratePerSecond)
        bucket.at = now
        this.buckets.set(key, bucket)
        if (bucket.tokens < 1) {
            return false
        }
        bucket.tokens -= 1
        return true
    }

    // Forgets the keys that have a full bucket again, so the map does not grow with every address that visits.
    prune(now: number): void {
        for (const [key, bucket] of this.buckets) {
            if (bucket.tokens + ((now - bucket.at) / 1000) * this.ratePerSecond >= this.burst) {
                this.buckets.delete(key)
            }
        }
    }
}
