import { CustomerioCampaignApi } from 'products/workflows/frontend/generated/api.schemas'

export interface ParsedCustomerioFile {
    campaigns: CustomerioCampaignApi[]
    snippets: Record<string, string>
}

type JsonObject = Record<string, unknown>

function isObject(value: unknown): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Templates as a list, from a list or from an object keyed by template id. */
function templateList(value: unknown): JsonObject[] {
    if (Array.isArray(value)) {
        return value.filter(isObject)
    }
    if (isObject(value)) {
        return Object.entries(value)
            .filter((entry): entry is [string, JsonObject] => isObject(entry[1]))
            .map(([id, template]) => ({ id, ...template }))
    }
    return []
}

/** One automation from the Customer.io CLI (`{campaign, actions}`), or the importer's own `{campaign, actions, templates}`. */
function toCampaign(value: unknown): CustomerioCampaignApi | null {
    if (!isObject(value) || !isObject(value.campaign) || !Array.isArray(value.actions)) {
        return null
    }
    return {
        campaign: value.campaign,
        actions: value.actions.filter(isObject),
        templates: templateList(value.templates),
    }
}

/** Whether a loose template belongs to one of the automation's steps, by template id or by step id. */
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
            const actions = campaign.actions as JsonObject[]
            const used = looseTemplates.filter((template) => isReferenced(template, actions))
            campaign.templates = [...templateList(campaign.templates), ...used]
        }
    }
    return { campaigns, snippets }
}
