#!/usr/bin/env tsx
/**
 * CLI entry. Two modes:
 *
 *   agent-migrate up [count]    — apply pending migrations
 *   agent-migrate down [count]  — revert last N (forward-only by convention, used for tests only)
 *
 * Reads AGENT_DB_URL (preferred) or DATABASE_URL.
 */

import { migrate } from './lib'

const direction = (process.argv[2] ?? 'up') as 'up' | 'down'
if (direction !== 'up' && direction !== 'down') {
    console.error(`Usage: agent-migrate up|down [count]`)
    process.exit(2)
}
const count = process.argv[3] ? Number(process.argv[3]) : undefined
if (count !== undefined && !Number.isFinite(count)) {
    console.error(`Usage: agent-migrate up|down [count]`)
    process.exit(2)
}

process.env.AGENT_MIGRATE_VERBOSE ??= '1'

const databaseUrl = process.env.AGENT_DB_URL ?? process.env.DATABASE_URL
if (!databaseUrl) {
    console.error(`agent-migrate: AGENT_DB_URL or DATABASE_URL must be set`)
    process.exit(2)
}

try {
    await migrate({ databaseUrl, direction, count })
} catch (err) {
    console.error(`agent-migrate: ${direction} failed`)
    console.error(err)
    process.exit(1)
}
