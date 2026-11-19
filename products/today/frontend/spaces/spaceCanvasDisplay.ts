import { IconDocument, IconGraph, IconLineGraph, IconPalette } from '@posthog/icons'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import type { TaskAvatarUser } from './TaskUserAvatar'

const TEMPLATE_ICONS: Record<string, typeof IconGraph> = {
    'web-analytics': IconLineGraph,
    blank: IconDocument,
    freeform: IconPalette,
}

export function spaceCanvasTemplateIcon(templateId: string): typeof IconGraph {
    return TEMPLATE_ICONS[templateId] ?? IconGraph
}

export function spaceCanvasAuthor(canvas: CanvasApi): TaskAvatarUser {
    return {
        uuid: canvas.created_by.uuid,
        email: canvas.created_by.email,
        first_name: canvas.created_by.first_name ?? '',
        last_name: canvas.created_by.last_name ?? '',
    }
}

export interface SpaceCanvasSections {
    pinned: CanvasApi[]
    rest: CanvasApi[]
}

export function spaceCanvasSections(canvases: CanvasApi[]): SpaceCanvasSections {
    const pinnedAt = (canvas: CanvasApi): number => (canvas.pinned_at ? Date.parse(canvas.pinned_at) : 0)
    return {
        pinned: canvases.filter((canvas) => canvas.pinned_at).sort((a, b) => pinnedAt(b) - pinnedAt(a)),
        rest: canvases.filter((canvas) => !canvas.pinned_at),
    }
}
