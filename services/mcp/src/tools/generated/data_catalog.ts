// AUTO-GENERATED from products/data_catalog/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DataCatalogCertificationsCertifyCreateParams,
    DataCatalogCertificationsCreateBody,
    DataCatalogCertificationsDeprecateCreateParams,
    DataCatalogMetricsApproveCreateParams,
    DataCatalogMetricsCreateBody,
    DataCatalogMetricsPartialUpdateBody,
    DataCatalogMetricsPartialUpdateParams,
    DataCatalogMetricsRunCreateBody,
    DataCatalogMetricsRunCreateParams,
    DataCatalogMetricsRunCreateQueryParams,
    DataCatalogRelationshipProposalsAcceptCreateParams,
    DataCatalogRelationshipProposalsCreateBody,
    DataCatalogRelationshipProposalsRejectCreateBody,
    DataCatalogRelationshipProposalsRejectCreateParams,
} from '@/generated/data_catalog/api'
import { getConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    executeConfirmedAction,
    prepareConfirmedAction,
    type PrepareConfirmedActionResult,
} from '@/tools/confirmed-action-runtime'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DataCatalogCertificationCertifySchema = DataCatalogCertificationsCertifyCreateParams.omit({ project_id: true })

const DataCatalogCertificationCertifySchemaExecute = DataCatalogCertificationCertifySchema.extend({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const dataCatalogCertificationCertifyPrepare = (): ToolBase<
    typeof DataCatalogCertificationCertifySchema,
    PrepareConfirmedActionResult
> => ({
    name: 'data-catalog-certification-certify-prepare',
    schema: DataCatalogCertificationCertifySchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogCertificationCertifySchema>) => {
        const __runtime = getConfirmedActionRuntime()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'data-catalog-certification-certify',
            actionLabel: 'certify source',
            messageTemplate:
                "About to mark certification '{id}' as certified (agents should prefer this source). Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
        })
    },
})

const dataCatalogCertificationCertifyExecute = (): ToolBase<
    typeof DataCatalogCertificationCertifySchemaExecute,
    Schemas.DataCatalogCertification
> => ({
    name: 'data-catalog-certification-certify-execute',
    schema: DataCatalogCertificationCertifySchemaExecute,
    handler: async (context: Context, params: z.infer<typeof DataCatalogCertificationCertifySchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __guard = await executeConfirmedAction(context, {
            incomingArgs: params,
            purpose: 'data-catalog-certification-certify',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        // Replace, do NOT merge: only signed fields are authorized. Any
        // base-schema field the model slipped into the execute call
        // (e.g. an unsigned 'name' alongside the signed 'enforce_2fa')
        // would otherwise survive into the downstream API body.
        // eslint-disable-next-line no-param-reassign
        params = { ...__guard.verifiedArgs } as typeof params
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataCatalogCertification>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/certifications/${encodeURIComponent(String(params.id))}/certify/`,
        })
        return result
    },
})

const DataCatalogCertificationDeprecateSchema = DataCatalogCertificationsDeprecateCreateParams.omit({
    project_id: true,
})

const DataCatalogCertificationDeprecateSchemaExecute = DataCatalogCertificationDeprecateSchema.extend({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const dataCatalogCertificationDeprecatePrepare = (): ToolBase<
    typeof DataCatalogCertificationDeprecateSchema,
    PrepareConfirmedActionResult
> => ({
    name: 'data-catalog-certification-deprecate-prepare',
    schema: DataCatalogCertificationDeprecateSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogCertificationDeprecateSchema>) => {
        const __runtime = getConfirmedActionRuntime()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'data-catalog-certification-deprecate',
            actionLabel: 'deprecate source',
            messageTemplate:
                "About to mark certification '{id}' as deprecated (agents should avoid this source). Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
        })
    },
})

const dataCatalogCertificationDeprecateExecute = (): ToolBase<
    typeof DataCatalogCertificationDeprecateSchemaExecute,
    Schemas.DataCatalogCertification
> => ({
    name: 'data-catalog-certification-deprecate-execute',
    schema: DataCatalogCertificationDeprecateSchemaExecute,
    handler: async (context: Context, params: z.infer<typeof DataCatalogCertificationDeprecateSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __guard = await executeConfirmedAction(context, {
            incomingArgs: params,
            purpose: 'data-catalog-certification-deprecate',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        // Replace, do NOT merge: only signed fields are authorized. Any
        // base-schema field the model slipped into the execute call
        // (e.g. an unsigned 'name' alongside the signed 'enforce_2fa')
        // would otherwise survive into the downstream API body.
        // eslint-disable-next-line no-param-reassign
        params = { ...__guard.verifiedArgs } as typeof params
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataCatalogCertification>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/certifications/${encodeURIComponent(String(params.id))}/deprecate/`,
        })
        return result
    },
})

const DataCatalogCertificationProposeSchema = DataCatalogCertificationsCreateBody

const dataCatalogCertificationPropose = (): ToolBase<
    typeof DataCatalogCertificationProposeSchema,
    Schemas.DataCatalogCertification
> => ({
    name: 'data-catalog-certification-propose',
    schema: DataCatalogCertificationProposeSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogCertificationProposeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.table_id !== undefined) {
            body['table_id'] = params.table_id
        }
        if (params.saved_query_id !== undefined) {
            body['saved_query_id'] = params.saved_query_id
        }
        if (params.table_name !== undefined) {
            body['table_name'] = params.table_name
        }
        if (params.view_name !== undefined) {
            body['view_name'] = params.view_name
        }
        if (params.notes !== undefined) {
            body['notes'] = params.notes
        }
        const result = await context.api.request<Schemas.DataCatalogCertification>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/certifications/`,
            body,
        })
        return result
    },
})

const DataCatalogMetricApproveSchema = DataCatalogMetricsApproveCreateParams.omit({ project_id: true })

const DataCatalogMetricApproveSchemaExecute = DataCatalogMetricApproveSchema.extend({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const dataCatalogMetricApprovePrepare = (): ToolBase<
    typeof DataCatalogMetricApproveSchema,
    PrepareConfirmedActionResult
> => ({
    name: 'data-catalog-metric-approve-prepare',
    schema: DataCatalogMetricApproveSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogMetricApproveSchema>) => {
        const __runtime = getConfirmedActionRuntime()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'data-catalog-metric-approve',
            actionLabel: 'approve metric',
            messageTemplate:
                "About to approve metric '{name}' as a canonical, human-vouched metric. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
        })
    },
})

const dataCatalogMetricApproveExecute = (): ToolBase<
    typeof DataCatalogMetricApproveSchemaExecute,
    Schemas.DataCatalogMetric
> => ({
    name: 'data-catalog-metric-approve-execute',
    schema: DataCatalogMetricApproveSchemaExecute,
    handler: async (context: Context, params: z.infer<typeof DataCatalogMetricApproveSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __guard = await executeConfirmedAction(context, {
            incomingArgs: params,
            purpose: 'data-catalog-metric-approve',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        // Replace, do NOT merge: only signed fields are authorized. Any
        // base-schema field the model slipped into the execute call
        // (e.g. an unsigned 'name' alongside the signed 'enforce_2fa')
        // would otherwise survive into the downstream API body.
        // eslint-disable-next-line no-param-reassign
        params = { ...__guard.verifiedArgs } as typeof params
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataCatalogMetric>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/metrics/${encodeURIComponent(String(params.name))}/approve/`,
        })
        return result
    },
})

const DataCatalogMetricCreateSchema = DataCatalogMetricsCreateBody

const dataCatalogMetricCreate = (): ToolBase<typeof DataCatalogMetricCreateSchema, Schemas.DataCatalogMetric> => ({
    name: 'data-catalog-metric-create',
    schema: DataCatalogMetricCreateSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogMetricCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.display_name !== undefined) {
            body['display_name'] = params.display_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.unit !== undefined) {
            body['unit'] = params.unit
        }
        if (params.definition !== undefined) {
            body['definition'] = params.definition
        }
        if (params.source_insight_short_id !== undefined) {
            body['source_insight_short_id'] = params.source_insight_short_id
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        const result = await context.api.request<Schemas.DataCatalogMetric>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/metrics/`,
            body,
        })
        return result
    },
})

const DataCatalogMetricRunSchema = DataCatalogMetricsRunCreateParams.omit({ project_id: true })
    .extend(DataCatalogMetricsRunCreateQueryParams.shape)
    .extend(DataCatalogMetricsRunCreateBody.shape)

const dataCatalogMetricRun = (): ToolBase<typeof DataCatalogMetricRunSchema, Schemas.DataCatalogMetricRun> => ({
    name: 'data-catalog-metric-run',
    schema: DataCatalogMetricRunSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogMetricRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.date_from !== undefined) {
            body['date_from'] = params.date_from
        }
        if (params.date_to !== undefined) {
            body['date_to'] = params.date_to
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.query_id !== undefined) {
            body['query_id'] = params.query_id
        }
        const result = await context.api.request<Schemas.DataCatalogMetricRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/metrics/${encodeURIComponent(String(params.name))}/run/`,
            body,
            query: {
                refresh: params.refresh,
            },
        })
        return result
    },
})

const DataCatalogMetricUpdateSchema = DataCatalogMetricsPartialUpdateParams.omit({ project_id: true }).extend(
    DataCatalogMetricsPartialUpdateBody.shape
)

const dataCatalogMetricUpdate = (): ToolBase<typeof DataCatalogMetricUpdateSchema, Schemas.DataCatalogMetric> => ({
    name: 'data-catalog-metric-update',
    schema: DataCatalogMetricUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogMetricUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.display_name !== undefined) {
            body['display_name'] = params.display_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.unit !== undefined) {
            body['unit'] = params.unit
        }
        if (params.definition !== undefined) {
            body['definition'] = params.definition
        }
        if (params.source_insight_short_id !== undefined) {
            body['source_insight_short_id'] = params.source_insight_short_id
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        const result = await context.api.request<Schemas.DataCatalogMetric>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/metrics/${encodeURIComponent(String(params.name))}/`,
            body,
        })
        return result
    },
})

const DataCatalogRelationshipAcceptSchema = DataCatalogRelationshipProposalsAcceptCreateParams.omit({
    project_id: true,
})

const DataCatalogRelationshipAcceptSchemaExecute = DataCatalogRelationshipAcceptSchema.extend({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const dataCatalogRelationshipAcceptPrepare = (): ToolBase<
    typeof DataCatalogRelationshipAcceptSchema,
    PrepareConfirmedActionResult
> => ({
    name: 'data-catalog-relationship-accept-prepare',
    schema: DataCatalogRelationshipAcceptSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogRelationshipAcceptSchema>) => {
        const __runtime = getConfirmedActionRuntime()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'data-catalog-relationship-accept',
            actionLabel: 'accept relationship',
            messageTemplate:
                "About to accept relationship proposal '{id}', promoting it to a real warehouse join. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
        })
    },
})

const dataCatalogRelationshipAcceptExecute = (): ToolBase<
    typeof DataCatalogRelationshipAcceptSchemaExecute,
    Schemas.DataCatalogRelationshipProposal
> => ({
    name: 'data-catalog-relationship-accept-execute',
    schema: DataCatalogRelationshipAcceptSchemaExecute,
    handler: async (context: Context, params: z.infer<typeof DataCatalogRelationshipAcceptSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __guard = await executeConfirmedAction(context, {
            incomingArgs: params,
            purpose: 'data-catalog-relationship-accept',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        // Replace, do NOT merge: only signed fields are authorized. Any
        // base-schema field the model slipped into the execute call
        // (e.g. an unsigned 'name' alongside the signed 'enforce_2fa')
        // would otherwise survive into the downstream API body.
        // eslint-disable-next-line no-param-reassign
        params = { ...__guard.verifiedArgs } as typeof params
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataCatalogRelationshipProposal>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/relationship_proposals/${encodeURIComponent(String(params.id))}/accept/`,
        })
        return result
    },
})

const DataCatalogRelationshipProposeSchema = DataCatalogRelationshipProposalsCreateBody

const dataCatalogRelationshipPropose = (): ToolBase<
    typeof DataCatalogRelationshipProposeSchema,
    Schemas.DataCatalogRelationshipProposal
> => ({
    name: 'data-catalog-relationship-propose',
    schema: DataCatalogRelationshipProposeSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogRelationshipProposeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_table_name !== undefined) {
            body['source_table_name'] = params.source_table_name
        }
        if (params.source_table_key !== undefined) {
            body['source_table_key'] = params.source_table_key
        }
        if (params.joining_table_name !== undefined) {
            body['joining_table_name'] = params.joining_table_name
        }
        if (params.joining_table_key !== undefined) {
            body['joining_table_key'] = params.joining_table_key
        }
        if (params.field_name !== undefined) {
            body['field_name'] = params.field_name
        }
        if (params.configuration !== undefined) {
            body['configuration'] = params.configuration
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        if (params.evidence !== undefined) {
            body['evidence'] = params.evidence
        }
        const result = await context.api.request<Schemas.DataCatalogRelationshipProposal>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/relationship_proposals/`,
            body,
        })
        return result
    },
})

const DataCatalogRelationshipRejectSchema = DataCatalogRelationshipProposalsRejectCreateParams.omit({
    project_id: true,
}).extend(DataCatalogRelationshipProposalsRejectCreateBody.shape)

const DataCatalogRelationshipRejectSchemaExecute = DataCatalogRelationshipRejectSchema.extend({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const dataCatalogRelationshipRejectPrepare = (): ToolBase<
    typeof DataCatalogRelationshipRejectSchema,
    PrepareConfirmedActionResult
> => ({
    name: 'data-catalog-relationship-reject-prepare',
    schema: DataCatalogRelationshipRejectSchema,
    handler: async (context: Context, params: z.infer<typeof DataCatalogRelationshipRejectSchema>) => {
        const __runtime = getConfirmedActionRuntime()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'data-catalog-relationship-reject',
            actionLabel: 'reject relationship',
            messageTemplate:
                "About to reject relationship proposal '{id}'. This permanently suppresses re-proposing the pair. Reply 'confirm' to proceed.\n",
            codec: __runtime.codec,
        })
    },
})

const dataCatalogRelationshipRejectExecute = (): ToolBase<
    typeof DataCatalogRelationshipRejectSchemaExecute,
    Schemas.DataCatalogRelationshipProposal
> => ({
    name: 'data-catalog-relationship-reject-execute',
    schema: DataCatalogRelationshipRejectSchemaExecute,
    handler: async (context: Context, params: z.infer<typeof DataCatalogRelationshipRejectSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __guard = await executeConfirmedAction(context, {
            incomingArgs: params,
            purpose: 'data-catalog-relationship-reject',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        // Replace, do NOT merge: only signed fields are authorized. Any
        // base-schema field the model slipped into the execute call
        // (e.g. an unsigned 'name' alongside the signed 'enforce_2fa')
        // would otherwise survive into the downstream API body.
        // eslint-disable-next-line no-param-reassign
        params = { ...__guard.verifiedArgs } as typeof params
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.rejection_reason !== undefined) {
            body['rejection_reason'] = params.rejection_reason
        }
        const result = await context.api.request<Schemas.DataCatalogRelationshipProposal>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_catalog/relationship_proposals/${encodeURIComponent(String(params.id))}/reject/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'data-catalog-certification-certify-prepare': dataCatalogCertificationCertifyPrepare,
    'data-catalog-certification-certify-execute': dataCatalogCertificationCertifyExecute,
    'data-catalog-certification-deprecate-prepare': dataCatalogCertificationDeprecatePrepare,
    'data-catalog-certification-deprecate-execute': dataCatalogCertificationDeprecateExecute,
    'data-catalog-certification-propose': dataCatalogCertificationPropose,
    'data-catalog-metric-approve-prepare': dataCatalogMetricApprovePrepare,
    'data-catalog-metric-approve-execute': dataCatalogMetricApproveExecute,
    'data-catalog-metric-create': dataCatalogMetricCreate,
    'data-catalog-metric-run': dataCatalogMetricRun,
    'data-catalog-metric-update': dataCatalogMetricUpdate,
    'data-catalog-relationship-accept-prepare': dataCatalogRelationshipAcceptPrepare,
    'data-catalog-relationship-accept-execute': dataCatalogRelationshipAcceptExecute,
    'data-catalog-relationship-propose': dataCatalogRelationshipPropose,
    'data-catalog-relationship-reject-prepare': dataCatalogRelationshipRejectPrepare,
    'data-catalog-relationship-reject-execute': dataCatalogRelationshipRejectExecute,
}
