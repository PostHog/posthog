import { Counter } from 'prom-client'

import { register } from '../metrics'

export type KmsOperation = 'generate_data_key' | 'decrypt' | 'rewrap'
export type KmsOutcome = 'ok' | 'unavailable' | 'rejected'

export const kmsCallsTotal = new Counter({
    name: 'credentials_service_kms_calls_total',
    help: 'Calls to the KMS provider, by operation and outcome',
    labelNames: ['op', 'outcome'],
    registers: [register],
})

// A miss is a `decrypt` call on kmsCallsTotal, so the hit rate needs no second counter.
export const dekCacheHitsTotal = new Counter({
    name: 'credentials_service_dek_cache_hits_total',
    help: 'Secret decryptions that found the unwrapped data key in the in-process cache',
    registers: [register],
})
