/**
 * Simple rate limiter to control request frequency
 * Uses a sliding window approach to limit requests per time period
 */
export class RateLimiter {
    private requestTimestamps: number[] = []
    private readonly maxRequests: number
    private readonly windowMs: number

    constructor(maxRequests: number = 10, windowMs: number = 1000) {
        this.maxRequests = maxRequests
        this.windowMs = windowMs
    }

    /**
     * Wait if necessary to respect rate limits, then record the request
     */
    async throttle(): Promise<void> {
        const now = Date.now()
        
        // Remove timestamps outside the current window
        this.requestTimestamps = this.requestTimestamps.filter(
            (timestamp) => now - timestamp < this.windowMs
        )

        // If we're at the limit, wait until the oldest request expires
        if (this.requestTimestamps.length >= this.maxRequests) {
            const oldestTimestamp = this.requestTimestamps[0]
            const waitTime = this.windowMs - (now - oldestTimestamp) + 10 // Add 10ms buffer
            
            if (waitTime > 0) {
                await new Promise((resolve) => setTimeout(resolve, waitTime))
            }
            
            // Clean up again after waiting
            const newNow = Date.now()
            this.requestTimestamps = this.requestTimestamps.filter(
                (timestamp) => newNow - timestamp < this.windowMs
            )
        }

        // Record this request
        this.requestTimestamps.push(Date.now())
    }

    /**
     * Reset the rate limiter state
     */
    reset(): void {
        this.requestTimestamps = []
    }
}

// Global rate limiter instance for API requests
// Set to 10 requests per second to be conservative
export const globalRateLimiter = new RateLimiter(10, 1000)
