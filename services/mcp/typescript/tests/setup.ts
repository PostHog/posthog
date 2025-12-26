import { config } from 'dotenv'
import { resolve } from 'node:path'
import { vi } from 'vitest'

// Load .env.test file
config({ path: resolve(process.cwd(), '.env.test') })

// Mock cloudflare:workers module for Node.js test environment
vi.mock('cloudflare:workers', () => ({
    env: {
        POSTHOG_BASE_URL: undefined, // Use default from constants
    },
}))
