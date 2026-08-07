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
import { providerForKey } from '../providers.js'
import type { SecretsSnapshot, SecretState } from '../types.js'
import type { UsageRecorder } from './recorder.js'

export const USAGE_OBJECT_KEY = 'integrations/usage/latest.json'

export interface UsageCallerEntry {
    /** The calling deployment, as authenticated by its signing key. */
    caller: string
    reads24h: number
    lastSeen: string | null
    /** True when this deployment has read the key since the current value was activated. */
    onCurrentValue: boolean
}

export interface UsageKeyEntry {
    provider: string
    state: SecretState
    currentVersionId: string
    currentActivatedAt: string | null
    callers: UsageCallerEntry[]
    /**
     * True when every deployment known to read this key has read it since the current
     * value became AWSCURRENT, and at least one such deployment exists.
     *
     * This is sound only because callers do not cache: a read after activation
     * necessarily returned the new value, so "has read since" means "is now using the
     * new value". If a client-side cache is ever reintroduced, this verdict stops
     * holding and has to be rethought.
     *
     * A deployment that reads the key rarely delays the verdict. That is the correct
     * direction to be wrong in.
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
    snapshot: SecretsSnapshot | null
    reads: ReadonlyMap<string, number>
    lastSeen: ReadonlyMap<string, number>
}): UsageMap {
    const keys: Record<string, UsageKeyEntry> = {}
    const snapshot = opts.snapshot

    if (snapshot) {
        for (const [key, resolved] of Object.entries(snapshot.secrets)) {
            const callers = new Map<string, UsageCallerEntry>()

            const ensure = (caller: string): UsageCallerEntry => {
                let entry = callers.get(caller)
                if (!entry) {
                    entry = { caller, reads24h: 0, lastSeen: null, onCurrentValue: false }
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

            const activatedAt = snapshot.versionCreatedAt ? Date.parse(snapshot.versionCreatedAt) : null
            for (const [field, at] of opts.lastSeen) {
                const [fieldKey, caller] = field.split('|')
                if (fieldKey === key && caller && callers.has(caller)) {
                    const entry = ensure(caller)
                    entry.lastSeen = new Date(at).toISOString()
                    // A read after activation necessarily returned the new value, because
                    // callers do not cache. So this is "has moved onto the new value".
                    entry.onCurrentValue = activatedAt !== null && at >= activatedAt
                }
            }

            const entries = [...callers.values()].sort((a, b) => a.caller.localeCompare(b.caller))

            keys[key] = {
                provider: providerForKey(key) ?? 'unknown',
                state: resolved.state,
                currentVersionId: resolved.versionId,
                currentActivatedAt: snapshot.versionCreatedAt,
                callers: entries,
                safeToRetirePrevious:
                    resolved.state === 'rotating' &&
                    entries.length > 0 &&
                    entries.every((entry) => entry.onCurrentValue),
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
    loadSnapshot: () => Promise<SecretsSnapshot | null>
}

export class UsagePublisher {
    constructor(private readonly opts: UsagePublisherOptions) {}

    async publish(): Promise<void> {
        try {
            const { reads, lastSeen } = await this.opts.recorder.summarize(this.opts.quietWindowHours)
            const usage = buildUsageMap({
                env: this.opts.env,
                generatedAt: new Date().toISOString(),
                quietWindowHours: this.opts.quietWindowHours,
                snapshot: await this.opts.loadSnapshot(),
                reads,
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
