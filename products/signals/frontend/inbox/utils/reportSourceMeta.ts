import api from 'lib/api'

import type { EmbeddingModelName } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { SignalReport } from '../types'

/** The row fields that come from ClickHouse. The list endpoint leaves them empty when the web inbox opts out. */
export type ReportSourceMeta = Pick<SignalReport, 'source_products' | 'scout_name'>

// Must match `EMBEDDING_MODEL` in products/signals/backend/signal_metadata.py.
const SIGNALS_EMBEDDING_MODEL: EmbeddingModelName = 'text-embedding-3-small-1536'

/**
 * Loads each report's distinct source products and authoring scout from the signal store. This is
 * the same query as `fetch_source_products_for_reports` on the backend. The inbox runs it after the
 * rows render, so the list does not wait on ClickHouse. Reports without signals get an empty entry,
 * so the caller does not ask for them again.
 */
export async function fetchReportSourceMeta(reportIds: string[]): Promise<Record<string, ReportSourceMeta>> {
    if (reportIds.length === 0) {
        return {}
    }
    const query = hogql`
        SELECT
            report_id,
            arraySort(groupUniqArray(source_product)) AS source_products,
            anyIf(skill_name, skill_name != '') AS scout_name
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') AS report_id,
                JSONExtractBool(metadata, 'deleted') AS is_deleted,
                JSONExtractString(metadata, 'source_product') AS source_product,
                JSONExtractString(metadata, 'extra', 'skill_name') AS skill_name
            FROM (
                SELECT argMax(metadata, inserted_at) AS metadata
                FROM document_embeddings
                WHERE model_name = ${SIGNALS_EMBEDDING_MODEL}
                  AND product = 'signals'
                  AND document_type = 'signal'
                  AND document_id IN (
                      SELECT DISTINCT document_id
                      FROM document_embeddings
                      WHERE model_name = ${SIGNALS_EMBEDDING_MODEL}
                        AND product = 'signals'
                        AND document_type = 'signal'
                        AND has(${reportIds}, JSONExtractString(metadata, 'report_id'))
                  )
                GROUP BY document_id
            )
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND has(${reportIds}, report_id)
          AND source_product != ''
        GROUP BY report_id
        LIMIT ${reportIds.length}`
    const response = await api.queryHogQL<[string, string[], string | null][]>(query, {
        scene: 'Inbox',
        productKey: 'signals',
    })
    const meta: Record<string, ReportSourceMeta> = Object.fromEntries(
        reportIds.map((id) => [id, { source_products: [], scout_name: null }])
    )
    for (const [reportId, sourceProducts, scoutName] of response.results ?? []) {
        meta[reportId] = { source_products: sourceProducts, scout_name: scoutName || null }
    }
    return meta
}
