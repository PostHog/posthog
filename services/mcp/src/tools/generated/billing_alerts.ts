// AUTO-GENERATED from products/billing_alerts/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    BillingAlertsCreateBody,
    BillingAlertsPartialUpdateBody,
    BillingAlertsPartialUpdateParams,
} from '@/generated/billing_alerts/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BillingAlertCreateSchema = BillingAlertsCreateBody

const billingAlertCreate = (): ToolBase<typeof BillingAlertCreateSchema, Schemas.BillingAlertConfiguration> => ({
    name: 'billing-alert-create',
    schema: BillingAlertCreateSchema,
    handler: async (context: Context, params: z.infer<typeof BillingAlertCreateSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.threshold_type !== undefined) {
            body['threshold_type'] = params.threshold_type
        }
        if (params.threshold_percentage !== undefined) {
            body['threshold_percentage'] = params.threshold_percentage
        }
        if (params.threshold_value !== undefined) {
            body['threshold_value'] = params.threshold_value
        }
        if (params.minimum_value !== undefined) {
            body['minimum_value'] = params.minimum_value
        }
        if (params.baseline_window_days !== undefined) {
            body['baseline_window_days'] = params.baseline_window_days
        }
        if (params.evaluation_delay_hours !== undefined) {
            body['evaluation_delay_hours'] = params.evaluation_delay_hours
        }
        if (params.cooldown_hours !== undefined) {
            body['cooldown_hours'] = params.cooldown_hours
        }
        if (params.snooze_until !== undefined) {
            body['snooze_until'] = params.snooze_until
        }
        if (params.destination_changes !== undefined) {
            body['destination_changes'] = params.destination_changes
        }
        const result = await context.api.request<Schemas.BillingAlertConfiguration>({
            method: 'POST',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/billing/alerts/`,
            body,
        })
        return result
    },
})

const BillingAlertUpdateSchema = BillingAlertsPartialUpdateParams.omit({ organization_id: true }).extend(
    BillingAlertsPartialUpdateBody.shape
)

const billingAlertUpdate = (): ToolBase<typeof BillingAlertUpdateSchema, Schemas.BillingAlertConfiguration> => ({
    name: 'billing-alert-update',
    schema: BillingAlertUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof BillingAlertUpdateSchema>) => {
        const orgId = await context.stateManager.getOrgID()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.threshold_type !== undefined) {
            body['threshold_type'] = params.threshold_type
        }
        if (params.threshold_percentage !== undefined) {
            body['threshold_percentage'] = params.threshold_percentage
        }
        if (params.threshold_value !== undefined) {
            body['threshold_value'] = params.threshold_value
        }
        if (params.minimum_value !== undefined) {
            body['minimum_value'] = params.minimum_value
        }
        if (params.baseline_window_days !== undefined) {
            body['baseline_window_days'] = params.baseline_window_days
        }
        if (params.evaluation_delay_hours !== undefined) {
            body['evaluation_delay_hours'] = params.evaluation_delay_hours
        }
        if (params.cooldown_hours !== undefined) {
            body['cooldown_hours'] = params.cooldown_hours
        }
        if (params.snooze_until !== undefined) {
            body['snooze_until'] = params.snooze_until
        }
        if (params.destination_changes !== undefined) {
            body['destination_changes'] = params.destination_changes
        }
        const result = await context.api.request<Schemas.BillingAlertConfiguration>({
            method: 'PATCH',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/billing/alerts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'billing-alert-create': billingAlertCreate,
    'billing-alert-update': billingAlertUpdate,
}
