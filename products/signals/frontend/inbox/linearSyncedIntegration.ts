import type { PaginatedResponse } from 'lib/api'

import { ExternalDataSource, IntegrationType } from '~/types'

/**
 * The Linear connection whose teams match the synced issues. The warehouse source records the
 * workspace it syncs, so its connection wins. Before a source exists, any Linear connection will do.
 */
export function syncedLinearIntegration(
    linearIntegrations: IntegrationType[],
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null
): IntegrationType | null {
    const syncedIntegrationId = dataWarehouseSources?.results.find(
        (source: ExternalDataSource) => source.source_type === 'Linear'
    )?.job_inputs?.linear_integration_id
    return (
        linearIntegrations.find((integration) => String(integration.id) === String(syncedIntegrationId)) ??
        linearIntegrations[0] ??
        null
    )
}
