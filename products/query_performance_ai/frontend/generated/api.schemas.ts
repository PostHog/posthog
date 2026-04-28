/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ExecuteTestClusterRequestApi {
    /**
     * ClickHouse SQL to run against the test cluster.
     * @maxLength 65536
     */
    sql: string
}

export interface ExecuteTestClusterResponseApi {
    /** Rows returned, each as a positional list of values from the ClickHouse driver. */
    result: unknown[][]
    /**
     * Server-side elapsed time in milliseconds.
     * @nullable
     */
    elapsed_ms: number | null
    /**
     * Rows read from storage (scan-side).
     * @nullable
     */
    rows_read: number | null
    /**
     * Bytes read from storage (scan-side).
     * @nullable
     */
    bytes_read: number | null
    /** Rows in the `result` payload. */
    rows_returned: number
    /** Server-minted query id; the caller can look this up in `system.query_log`. */
    query_id: string
}
