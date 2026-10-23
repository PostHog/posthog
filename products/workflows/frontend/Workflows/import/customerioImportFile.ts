import { CustomerioCampaignApi } from 'products/workflows/frontend/generated/api.schemas'

export interface ParsedCustomerioFile {
    campaigns: CustomerioCampaignApi[]
    snippets: Record<string, string>
}

type JsonObject = Record<string, unknown>

function isObject(value: unknown): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** One automation from the Customer.io CLI (`{campaign, actions}`), or the importer's own `{campaign, actions, templates}`. */
function toCampaign(value: unknown): CustomerioCampaignApi | null {
    if (!isObject(value) || !isObject(value.campaign) || !Array.isArray(value.actions)) {
        return null
    }
    return {
        campaign: value.campaign,
        actions: value.actions.filter(isObject),
        templates: value.templates ?? [],
    }
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
 * them, `{campaigns: [...]}`, and loose template files, which attach to every automation that points at them.
 */
export function parseCustomerioFiles(contents: string[]): ParsedCustomerioFile {
    const campaigns: CustomerioCampaignApi[] = []
    const looseTemplates: JsonObject[] = []
    let snippets: Record<string, string> = {}

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
                value.campaigns.forEach(collect)
            }
            if (Array.isArray(value.templates)) {
                value.templates.forEach(collect)
            }
            if (isObject(value.snippets)) {
                snippets = { ...snippets, ...(value.snippets as Record<string, string>) }
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
            const own = Array.isArray(campaign.templates) ? (campaign.templates as JsonObject[]) : []
            campaign.templates = [...own, ...looseTemplates]
        }
    }
    return { campaigns, snippets }
}
