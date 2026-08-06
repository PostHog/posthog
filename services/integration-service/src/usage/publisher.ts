// Publishes the usage rollup to the secrets index bucket as
// `integrations/usage/latest.json`.
//
// PostHog/secrets already reads two artifacts from that bucket through
// packages/core/src/index-store.ts: `consumption/latest.json` (which app DECLARES it
// consumes which key, rendered from charts' ExternalSecrets) and `secrets/latest.json`
// (which keys exist where). This is the third: which caller ACTUALLY read which key.
//
// The declared-vs-observed difference is the useful part. It answers "charts grants
// the worker this key but nothing has ever read it", which is how a duplicated env var
// gets proven dead before anyone deletes it.
//
// The artifact carries no credential values — caller names, key names, counts,
// timestamps and rotation state only.

import { PutObjectCommand, type S3Client } from '@aws-sdk/client-s3'

import { logger } from '../lib/logging.js'
import { usagePublishTotal } from '../metrics.js'
import { PROVIDER_NAMES, providerForKey } from '../providers.js'
import type { ProviderSnapshot, SecretState } from '../types.js'
import type { UsageRecorder } from './recorder.js'

export const USAGE_OBJECT_KEY = 'integrations/usage/latest.json'

export interface UsageCallerEntry {
    caller: string
    reads24h: number
    previousUsed24h: number
    lastSeen: string | null
}

export interface UsageKeyEntry {
    provider: string
    state: SecretState
    currentVersionId: string
    currentActivatedAt: string | null
    callers: UsageCallerEntry[]
    /**
     * True only when BOTH hold: nobody has needed the previous value across the quiet
     * window, AND at least one caller has successfully read the current value in it.
     *
     * The second condition is not redundant. Zero previous-value use on its own is
     * equally consistent with nothing reading the credential at all, which is exactly
     * the state in which retiring a value looks safe and is not.
     */
    safeToRetirePrevious: boolean
}

export interface UsageMap {
    generatedAt: string
    env: string
    /** Hours of quiet required before safeToRetirePrevious can be true. */
    quietWindowHours: number
    keys: Record<string, UsageKeyEntry>
}

export function buildUsageMap(opts: {
    env: string
    generatedAt: string
    quietWindowHours: number
    snapshots: readonly ProviderSnapshot[]
    reads: ReadonlyMap<string, number>
    previousUsed: ReadonlyMap<string, number>
    lastSeen: ReadonlyMap<string, number>
}): UsageMap {
    const keys: Record<string, UsageKeyEntry> = {}

    for (const snapshot of opts.snapshots) {
        for (const [key, resolved] of Object.entries(snapshot.secrets)) {
            const callers = new Map<string, UsageCallerEntry>()

            const ensure = (caller: string): UsageCallerEntry => {
                let entry = callers.get(caller)
                if (!entry) {
                    entry = { caller, reads24h: 0, previousUsed24h: 0, lastSeen: null }
                    callers.set(caller, entry)
                }
                return entry
            }

            for (const [field, count] of opts.reads) {
                const [fieldKey, caller] = field.split('|')
                if (fieldKey === key && caller) {
                    ensure(caller).reads24h += count
                }
            }
            for (const [field, count] of opts.previousUsed) {
                const [fieldKey, caller] = field.split('|')
                if (fieldKey === key && caller) {
                    ensure(caller).previousUsed24h += count
                }
            }
            for (const [field, at] of opts.lastSeen) {
                const [fieldKey, caller] = field.split('|')
                if (fieldKey === key && caller && callers.has(caller)) {
                    ensure(caller).lastSeen = new Date(at).toISOString()
                }
            }

            const entries = [...callers.values()].sort((a, b) => a.caller.localeCompare(b.caller))
            const anyPreviousUsed = entries.some((entry) => entry.previousUsed24h > 0)
            const anyCurrentRead = entries.some((entry) => entry.reads24h > 0)

            keys[key] = {
                provider: providerForKey(key) ?? snapshot.provider,
                state: resolved.state,
                currentVersionId: resolved.versionId,
                currentActivatedAt: snapshot.currentActivatedAt,
                callers: entries,
                safeToRetirePrevious: resolved.state === 'rotating' && !anyPreviousUsed && anyCurrentRead,
            }
        }
    }

    return {
        generatedAt: opts.generatedAt,
        env: opts.env,
        quietWindowHours: opts.quietWindowHours,
        keys,
    }
}

export interface UsagePublisherOptions {
    s3: S3Client
    bucket: string
    kmsKeyId?: string | undefined
    env: string
    quietWindowHours: number
    recorder: UsageRecorder
    loadSnapshot: (provider: string) => Promise<ProviderSnapshot | null>
}

export class UsagePublisher {
    constructor(private readonly opts: UsagePublisherOptions) {}

    async publish(): Promise<void> {
        try {
            const { reads, previousUsed, lastSeen } = await this.opts.recorder.summarize(this.opts.quietWindowHours)
            const snapshots = (await Promise.all(PROVIDER_NAMES.map((p) => this.opts.loadSnapshot(p)))).filter(
                (s): s is ProviderSnapshot => s !== null
            )

            const usage = buildUsageMap({
                env: this.opts.env,
                generatedAt: new Date().toISOString(),
                quietWindowHours: this.opts.quietWindowHours,
                snapshots,
                reads,
                previousUsed,
                lastSeen,
            })

            await this.opts.s3.send(
                new PutObjectCommand({
                    Bucket: this.opts.bucket,
                    Key: USAGE_OBJECT_KEY,
                    Body: JSON.stringify(usage),
                    ContentType: 'application/json',
                    ...(this.opts.kmsKeyId
                        ? { ServerSideEncryption: 'aws:kms' as const, SSEKMSKeyId: this.opts.kmsKeyId }
                        : {}),
                })
            )
            usagePublishTotal.labels({ result: 'ok' }).inc()
            logger.info('usage:published', { keys: Object.keys(usage.keys).length })
        } catch (err) {
            usagePublishTotal.labels({ result: 'error' }).inc()
            logger.error('usage:publish_failed', { error: err instanceof Error ? err.message : String(err) })
        }
    }
}
