import { isEmail } from 'lib/utils/url'

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

/** Snippets as the importer's own name to content map, or the list the CLI returns. */
function snippetsIn(value: unknown): Record<string, string> {
    if (Array.isArray(value)) {
        return Object.fromEntries(
            value
                .filter((snippet) => isObject(snippet) && snippet.name)
                .map((snippet) => [String(snippet.name), String(snippet.value ?? '')])
        )
    }
    return isObject(value) ? (value as Record<string, string>) : {}
}

/** Layouts as the importer's own id to body map, or the CLI's `{layout}` and `{layouts: [...]}`, which templates carry too. */
function layoutsIn(value: unknown): Record<string, string> {
    if (!isObject(value)) {
        return {}
    }
    if (isObject(value.layouts)) {
        return value.layouts as Record<string, string>
    }
    const layouts = Array.isArray(value.layouts) ? value.layouts : [value.layout]
    return Object.fromEntries(
        layouts
            .filter((layout) => isObject(layout) && layout.id !== undefined && typeof layout.body === 'string')
            .map((layout) => [String(layout.id), layout.body])
    )
}

/** The CLI's identities also hold phone numbers and senders with no fixed address, which one email can't match. */
function identitiesIn(value: unknown): CustomerioSenderIdentityApi[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value
        .filter((identity) => isObject(identity) && isEmail(String(identity.email ?? '')))
        .map((identity) => ({
            id: String(identity.id),
            email: identity.email,
            name: String(identity.name ?? ''),
        }))
}

function segmentsIn(value: JsonObject): CustomerioSegmentApi[] {
    if (Array.isArray(value.segments)) {
        return value.segments as CustomerioSegmentApi[]
    }
    if (isObject(value.segment) && value.segment.id !== undefined) {
        return [value.segment as unknown as CustomerioSegmentApi]
    }
    return []
}

/**
 * Reads the automations out of files a person saved from the Customer.io CLI or MCP. Accepts one automation, a list of
 * them, `{campaigns: [...]}`, loose template files, which attach to the automations whose steps use them, and segment
 * files, whose rules let the import turn a segment into a cohort.
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
            layouts = { ...layouts, ...layoutsIn(value) }
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
            snippets = { ...snippets, ...snippetsIn(value.snippets) }
            layouts = { ...layouts, ...layoutsIn(value) }
            if (isObject(value.segment_cohorts)) {
                segmentCohorts = { ...segmentCohorts, ...(value.segment_cohorts as Record<string, number>) }
            }
            if (Array.isArray(value.sender_identities)) {
                senderIdentities.push(...(value.sender_identities as CustomerioSenderIdentityApi[]))
            }
            senderIdentities.push(...identitiesIn(value.identities))
            segments.push(...segmentsIn(value))
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
