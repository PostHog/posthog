import type { ContentBlock } from '../acp-types'
import { getFileName } from './path'

/**
 * Vendored from apps/code/src/renderer/utils/promptContent.ts. Extracts the
 * displayable text and attachment refs from a user prompt's content blocks.
 */

export const ATTACHMENT_URI_PREFIX = 'attachment://'

export interface AttachmentRef {
    id: string
    label: string
}

export function parseAttachmentUri(uri: string): AttachmentRef | null {
    if (!uri.startsWith(ATTACHMENT_URI_PREFIX)) {
        return null
    }

    const rawValue = uri.slice(ATTACHMENT_URI_PREFIX.length)
    const queryStart = rawValue.indexOf('?')
    if (queryStart < 0) {
        return null
    }

    const label =
        decodeURIComponent(new URLSearchParams(rawValue.slice(queryStart + 1)).get('label') ?? '') || 'attachment'

    return { id: uri, label }
}

function parseFileUri(uri: string, fallbackLabel?: string): AttachmentRef | null {
    if (!uri.startsWith('file://')) {
        return null
    }

    try {
        const pathname = decodeURIComponent(new URL(uri).pathname)
        const label = fallbackLabel?.trim() || getFileName(pathname) || 'attachment'
        return { id: uri, label }
    } catch {
        const label = fallbackLabel?.trim() || getFileName(uri) || 'attachment'
        return { id: uri, label }
    }
}

function getBlockAttachmentRef(block: ContentBlock): AttachmentRef | null {
    if (block.type === 'resource') {
        const uri = block.resource.uri
        if (!uri) {
            return null
        }
        return parseAttachmentUri(uri) ?? parseFileUri(uri)
    }

    if (block.type === 'image') {
        const uri = block.uri
        if (!uri) {
            return null
        }
        return parseAttachmentUri(uri) ?? parseFileUri(uri)
    }

    if (block.type === 'resource_link') {
        return parseAttachmentUri(block.uri) ?? parseFileUri(block.uri, block.name)
    }

    return null
}

export interface PromptDisplayContent {
    text: string
    attachments: AttachmentRef[]
}

export function extractPromptDisplayContent(
    blocks: ContentBlock[],
    options?: { filterHidden?: boolean }
): PromptDisplayContent {
    const filterHidden = options?.filterHidden ?? false

    const textParts: string[] = []
    for (const block of blocks) {
        if (block.type !== 'text') {
            continue
        }
        if (filterHidden) {
            const meta = (block as { _meta?: { ui?: { hidden?: boolean } } })._meta
            if (meta?.ui?.hidden) {
                continue
            }
        }
        textParts.push(block.text)
    }

    const seen = new Set<string>()
    const attachments: AttachmentRef[] = []
    for (const block of blocks) {
        const ref = getBlockAttachmentRef(block)
        if (!ref || seen.has(ref.id)) {
            continue
        }
        const { id } = ref
        if (!id) {
            continue
        }
        seen.add(id)
        attachments.push(ref)
    }

    return { text: textParts.join(''), attachments }
}
