import { Counter, Gauge } from 'prom-client'

import { register } from '../metrics'

export type AuditExportOutcome = 'sent' | 'failed'

export const auditExportedTotal = new Counter({
    name: 'credentials_service_audit_exported_total',
    help: 'Audit rows sent to the capture endpoint, by outcome. A failed row is retried',
    labelNames: ['outcome'],
    registers: [register],
})

export const auditExportLagSeconds = new Gauge({
    name: 'credentials_service_audit_export_lag_seconds',
    help: 'Age of the oldest audit row that is not exported yet. 0 when none is waiting',
    registers: [register],
})
