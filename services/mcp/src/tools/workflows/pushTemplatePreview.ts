import { createHash } from 'node:crypto'

import type { Schemas } from '@/api/generated'
import { PostHogApiError, PostHogPermissionError, ToolInputValidationError } from '@/lib/errors'
import { quoteUntrusted } from '@/lib/quote-untrusted'
import { describeLinkTarget, describeVariables } from '@/lib/untrusted-link'
import type { ConfirmedActionPreviewLoader } from '@/tools/confirmed-action-runtime'
import type { Context } from '@/tools/types'

const MAX_NAME_CHARACTERS = 100
const MAX_TITLE_CHARACTERS = 200
const MAX_BODY_CHARACTERS = 500
const MAX_LINK_CHARACTERS = 500
const MAX_DATA_CHARACTERS = 200
const MAX_DATA_KEYS = 50

const CHANNEL_KINDS: Record<string, string> = { firebase: 'Firebase', apns: 'Apple (APNs)' }

function show(value: unknown, maxCharacters: number): string {
    if (typeof value !== 'string' || value === '') {
        return '(empty)'
    }
    return quoteUntrusted(value, maxCharacters)
}

function showFilled(value: unknown, maxCharacters: number): string {
    return show(value, maxCharacters) + (typeof value === 'string' ? describeVariables(value) : '')
}

function showLink(value: unknown): string {
    if (typeof value !== 'string' || value === '') {
        return '(none)'
    }
    return showFilled(value, MAX_LINK_CHARACTERS) + describeLinkTarget(value)
}

// The app reads these from the data, so a template can set them there too. Link and Image win when they are not empty.
const DATA_KEY_NOTES = new Map([
    ['link', ' [where a tap goes when Link is empty]'],
    ['image_url', ' [the image on iOS when Image is empty]'],
])

// Looser than a URL, because URL parsers also accept one slash, a backslash or none.
const LINK_LIKE = /^\s*(?:https?:|[a-z][a-z0-9+.-]*:[/\\])/i

function describeData(data: Record<string, unknown>): string[] {
    const keys = Object.keys(data).sort((a, b) => Number(DATA_KEY_NOTES.has(b)) - Number(DATA_KEY_NOTES.has(a)))
    if (keys.length === 0) {
        return ['Data: (none)']
    }
    const lines = keys.slice(0, MAX_DATA_KEYS).map((key) => {
        const value = typeof data[key] === 'string' ? data[key] : JSON.stringify(data[key])
        const note = DATA_KEY_NOTES.get(key) ?? ''
        const target = describeLinkTarget(value)
        const isLink = !!note || target.startsWith(' [host') || LINK_LIKE.test(value.replace(/[\t\n\r]/g, ''))
        return `Data ${quoteUntrusted(key, MAX_NAME_CHARACTERS)}: ${showFilled(value, MAX_DATA_CHARACTERS)}${value && isLink ? target : ''}${note}`
    })
    const hidden = keys.length - lines.length
    return hidden > 0 ? [...lines, `Data: [cut: ${hidden} more keys]`] : lines
}

async function describeChannel(context: Context, projectId: string, id: number): Promise<string> {
    try {
        const integration = await context.api.request<{ kind?: string; display_name?: string | null }>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/integrations/${encodeURIComponent(String(id))}/`,
        })
        const kind = CHANNEL_KINDS[integration.kind ?? ''] ?? 'not a push channel'
        return `${kind} ${show(integration.display_name, MAX_NAME_CHARACTERS)} (ID ${id})`
    } catch (error) {
        if (error instanceof PostHogApiError && error.status === 404) {
            return `not found in this project (ID ${id})`
        }
        if (error instanceof PostHogPermissionError) {
            return `name not readable with this connection (ID ${id})`
        }
        throw error
    }
}

const previewPushTemplate: ConfirmedActionPreviewLoader<{ id: string }> = async (context, params, scope) => {
    const projectId = scope.projectId!
    const template = await context.api.request<Schemas.MessageTemplate>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/messaging_templates/${encodeURIComponent(params.id)}/`,
    })
    if (template.id?.toLowerCase() !== params.id.toLowerCase()) {
        throw new ToolInputValidationError('This is not a template ID.')
    }
    if (template.type !== 'push') {
        throw new ToolInputValidationError('This is not a push template.')
    }
    const push = template.content?.push
    const channelIds = [...new Set(push?.channels ?? [])]
    const channels = await Promise.all(channelIds.map((id) => describeChannel(context, projectId, id)))
    const lines = [
        `Template ID: ${template.id}`,
        `Name: ${show(template.name, MAX_NAME_CHARACTERS)}`,
        `Title: ${showFilled(push?.title, MAX_TITLE_CHARACTERS)}`,
        `Body: ${showFilled(push?.body, MAX_BODY_CHARACTERS)}`,
        `Link: ${showLink(push?.link)}`,
        `Image: ${showLink(push?.image)}`,
        ...describeData(push?.data ?? {}),
        ...(channels.length ? channels.map((channel) => `Channel: ${channel}`) : ['Channel: (none)']),
        ...(template.transactional_hog_flow_id
            ? ['Already sendable: its workflow sends it, and can hold settings that are not shown here.']
            : []),
    ]
    return {
        text: ['```text', ...lines, '```'].join('\n'),
        fingerprint: createHash('sha256')
            .update(
                JSON.stringify([
                    template.id,
                    template.name,
                    template.content,
                    template.transactional_hog_flow_id,
                    channels,
                ])
            )
            .digest('hex'),
    }
}

export default previewPushTemplate
