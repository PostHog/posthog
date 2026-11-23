import { LogsAlertSimulateBucketApi } from 'products/logs/frontend/generated/api.schemas'

export const SIMULATION_RANGE_OPTIONS = [
    { value: '-1h', label: 'Last 1 hour' },
    { value: '-6h', label: 'Last 6 hours' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
]

export interface Incident {
    firedAt: string
    resolvedAt: string | null
    durationMinutes: number
    peakCount: number
    stillFiring: boolean
}

export function extractIncidents(buckets: LogsAlertSimulateBucketApi[]): Incident[] {
    const incidents: Incident[] = []
    let currentIncident: Incident | null = null

    for (const b of buckets) {
        if (b.state === 'firing' || b.state === 'pending_resolve') {
            if (!currentIncident) {
                currentIncident = {
                    firedAt: b.timestamp,
                    resolvedAt: null,
                    durationMinutes: 1,
                    peakCount: b.count,
                    stillFiring: true,
                }
            } else {
                currentIncident.durationMinutes += 1
                currentIncident.peakCount = Math.max(currentIncident.peakCount, b.count)
            }
        } else if (currentIncident) {
            currentIncident.resolvedAt = b.timestamp
            currentIncident.stillFiring = false
            incidents.push(currentIncident)
            currentIncident = null
        }
    }
    if (currentIncident) {
        incidents.push(currentIncident)
    }
    return incidents
}
