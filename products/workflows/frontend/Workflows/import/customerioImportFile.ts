import {
    CustomerioCampaignApi,
    CustomerioSegmentApi,
    CustomerioSenderIdentityApi,
    WorkflowImportRequestApi,
} from 'products/workflows/frontend/generated/api.schemas'

export type ParsedCustomerioFile = Pick<
    WorkflowImportRequestApi,
    'campaigns' | 'layouts' | 'segment_cohorts' | 'sender_identities' | 'segments'
> & { snippets: Record<string, string> }

type JsonObject = Record<string, unknown>

function isObject(value: unknown): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Templates as a list, or null when they are malformed, so the request keeps them and the API rejects it. */
function templateList(value: unknown): JsonObject[] | null {
    if (value === undefined || value === null) {
        return []
    }
    if (Array.isArray(value)) {
        return value.every(isObject) ? value : null
    }
    if (isObject(value)) {
        const entries = Object.entries(value)
        return entries.every(([, template]) => isObject(template))
            ? entries.map(([id, template]) => ({ ...(template as JsonObject), id }))
            : null
    }
    return null
}

/** One automation from the Customer.io CLI (`{campaign, actions}`), or the importer's own `{campaign, actions, templates}`. */
function toCampaign(value: unknown): CustomerioCampaignApi | null {
    if (!isObject(value) || !isObject(value.campaign) || !Array.isArray(value.actions)) {
        return null
    }
    return {
        campaign: value.campaign,
        // Kept as is, so the API rejects a malformed step instead of the preview hiding it.
        actions: value.actions as JsonObject[],
        templates: templateList(value.templates) ?? value.templates,
    }
}

function isReferenced(template: JsonObject, actions: JsonObject[]): boolean {
    return actions.some(
        (action) =>
            (action.template_id !== undefined && String(action.template_id) === String(template.id)) ||
            (template.action_id !== undefined && String(template.action_id) === String(action.id))
    )
}

/** A template from `GET .../templates/{id}`, which the CLI wraps as `{template: {...}}`. */
function toTemplate(value: unknown): JsonObject | null {
    if (isObject(value) && isObject(value.template)) {
        return value.template
    }
    return isObject(value) && value.id !== undefined && ('body' in value || 'subject' in value) ? value : null
}

/**
 * Reads the automations out of files a person saved from the Customer.io CLI or MCP. Accepts one automation, a list of
 * them, `{campaigns: [...]}`, and loose template files, which attach to the automations whose steps use them.
 */
export function parseCustomerioFiles(contents: string[]): ParsedCustomerioFile {
    const campaigns: CustomerioCampaignApi[] = []
    const looseTemplates: JsonObject[] = []
    let snippets: Record<string, string> = {}
    let layouts: Record<string, string> = {}
    let segmentCohorts: Record<string, number> = {}
    const senderIdentities: CustomerioSenderIdentityApi[] = []
    const segments: CustomerioSegmentApi[] = []

    const collect = (value: unknown): void => {
        if (Array.isArray(value)) {
            value.forEach(collect)
            return
        }
        const campaign = toCampaign(value)
        if (campaign) {
            campaigns.push(campaign)
            return
        }
        const template = toTemplate(value)
        if (template) {
            looseTemplates.push(template)
            return
        }
        if (isObject(value)) {
            if (Array.isArray(value.campaigns)) {
                for (const entry of value.campaigns) {
                    // A malformed entry is kept as is, so the API rejects the request instead of dropping it.
                    campaigns.push(toCampaign(entry) ?? (entry as CustomerioCampaignApi))
                }
            }
            if (Array.isArray(value.templates)) {
                value.templates.forEach(collect)
            }
            if (isObject(value.snippets)) {
                snippets = { ...snippets, ...(value.snippets as Record<string, string>) }
            }
            if (isObject(value.layouts)) {
                layouts = { ...layouts, ...(value.layouts as Record<string, string>) }
            }
            if (isObject(value.segment_cohorts)) {
                segmentCohorts = { ...segmentCohorts, ...(value.segment_cohorts as Record<string, number>) }
            }
            if (Array.isArray(value.sender_identities)) {
                senderIdentities.push(...(value.sender_identities as CustomerioSenderIdentityApi[]))
            }
            if (Array.isArray(value.segments)) {
                segments.push(...(value.segments as CustomerioSegmentApi[]))
            }
        }
    }

    for (const content of contents) {
        try {
            collect(JSON.parse(content))
        } catch {
            throw new Error('One of the files is not valid JSON.')
        }
    }

    if (looseTemplates.length) {
        for (const campaign of campaigns) {
            const actions = campaign.actions as JsonObject[]
            const templates = templateList(campaign.templates)
            if (!templates || !Array.isArray(actions)) {
                continue
            }
            const used = looseTemplates.filter((template) => isReferenced(template, actions))
            campaign.templates = [...templates, ...used]
        }
    }
    return {
        campaigns,
        snippets,
        layouts,
        segment_cohorts: segmentCohorts,
        sender_identities: senderIdentities,
        segments,
    }
}
