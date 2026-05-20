/**
 * Confirmation builders — per-tool functions that produce a `{ title, description }`
 * for the elicitation modal at runtime, using resolved tool params (and optional
 * server-side data, e.g. fetched entity names).
 *
 * Sensitive tools opt in via `confirmation_required: true` + `confirmation_builder: <name>`
 * in their YAML. The codegen imports the named builder and calls it before invoking
 * `confirmAction()`. Each builder must be a `(context, params) => Promise<ConfirmActionInput>`.
 *
 * Keep these functions narrow: don't perform side effects, don't throw on missing
 * data — return the best human-readable message you can. The builder runs before
 * the actual destructive request, so it must be safe to call even on declined paths.
 */

import type { Schemas } from '@/api/generated'
import type { ConfirmActionInput } from '@/lib/confirm-action'
import type { Context } from '@/tools/types'

type Enforce2faParams = {
    id: string
    enforce_2fa?: boolean | null | undefined
}

export async function buildEnforce2faConfirmation(
    context: Context,
    params: Enforce2faParams
): Promise<ConfirmActionInput> {
    const verb = params.enforce_2fa === true ? 'Enable' : params.enforce_2fa === false ? 'Disable' : 'Clear'

    let orgLabel = params.id
    try {
        const org = await context.api.request<Schemas.Organization>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(params.id))}/`,
        })
        if (org?.name && org?.id) {
            orgLabel = `${org.name} (${org.id})`
        }
    } catch {
        // Fall back to the raw id — surfacing the change is more important than the name lookup.
    }

    return {
        title: `${verb} 2FA enforcement`,
        description: `Action: ${verb} 2FA enforcement\nOrganization: ${orgLabel}`,
    }
}
