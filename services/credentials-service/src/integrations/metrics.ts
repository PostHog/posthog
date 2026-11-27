import { Counter } from 'prom-client'

import { register } from '../metrics'

export type AuditDropReason = 'queue_full' | 'write_failed'

// Reads never wait for the audit write, so a dropped row is the only sign of a gap in the trail.
export const auditDroppedTotal = new Counter({
    name: 'credentials_service_audit_dropped_total',
    help: 'Read audit rows dropped before they reached the database, by reason',
    labelNames: ['reason'],
    registers: [register],
})

export const auditWrittenTotal = new Counter({
    name: 'credentials_service_audit_written_total',
    help: 'Audit rows written by the async read queue',
    registers: [register],
})

export const mirrorRowsTotal = new Counter({
    name: 'credentials_service_integration_mirror_rows_total',
    help: 'Rows of PUT /v1/integrations/mirror, by origin and outcome',
    labelNames: ['origin', 'outcome'],
    registers: [register],
})

export const mirrorPurgeRowsTotal = new Counter({
    name: 'credentials_service_integration_mirror_purge_rows_total',
    help: 'Rows of POST /v1/integrations/mirror/purge, by outcome (purged, or dry_run for a row a dry run matched)',
    labelNames: ['outcome'],
    registers: [register],
})
