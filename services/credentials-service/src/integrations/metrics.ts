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
