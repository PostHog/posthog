import { createHash } from 'node:crypto'

import type { Schemas } from '@/api/generated'
import { PostHogApiError, PostHogPermissionError, ToolInputValidationError } from '@/lib/errors'
import { quoteUntrusted } from '@/lib/quote-untrusted'
import type { ConfirmedActionPreviewLoader } from '@/tools/confirmed-action-runtime'
import type { Context } from '@/tools/types'

const MAX_NAME_CHARACTERS = 100
const MAX_TITLE_CHARACTERS = 200
const MAX_BODY_CHARACTERS = 500

const CHANNEL_KINDS: Record<string, string> = { firebase: 'Firebase', apns: 'Apple (APNs)' }

function show(value: unknown, maxCharacters: number): string {
    if (typeof value !== 'string' || value === '') {
        return '(empty)'
    }
    return quoteUntrusted(value, maxCharacters)
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
        `Title: ${show(push?.title, MAX_TITLE_CHARACTERS)}`,
        `Body: ${show(push?.body, MAX_BODY_CHARACTERS)}`,
        ...(channels.length ? channels.map((channel) => `Channel: ${channel}`) : ['Channel: (none)']),
    ]
    return {
        text: ['```text', ...lines, '```'].join('\n'),
        fingerprint: createHash('sha256')
            .update(JSON.stringify([template.id, template.name, template.content, channels]))
            .digest('hex'),
    }
}

export default previewPushTemplate
