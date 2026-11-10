import { loadConfig } from './lib/config'
import { logger } from './lib/logging'
import { CredentialsServer } from './server'

async function main(): Promise<void> {
    await new CredentialsServer(loadConfig()).start()
}

main().catch((err: unknown) => {
    logger.error('fatal', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
