import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { ExecuteTestClusterRequestApi, ExecuteTestClusterResponseApi } from './api.schemas'

/**
 * DEBUG-only proxy that forwards SQL to the ClickHouse `autoresearch` user. SQL safety comes entirely from the CH user's grants + readonly=2 profile; the endpoint does not parse or filter SQL.
 * @summary Run a read-only query against the autoresearch test cluster
 */
export const getQueryPerformanceProxyExecuteTestCreateUrl = () => {
    return `/api/query_performance_proxy/execute-test/`
}

export const queryPerformanceProxyExecuteTestCreate = async (
    executeTestClusterRequestApi: ExecuteTestClusterRequestApi,
    options?: RequestInit
): Promise<ExecuteTestClusterResponseApi> => {
    return apiMutator<ExecuteTestClusterResponseApi>(getQueryPerformanceProxyExecuteTestCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(executeTestClusterRequestApi),
    })
}
