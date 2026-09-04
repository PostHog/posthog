import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

/** Every Replay vision scene hangs off this crumb, so it lives in one place rather than six. */
export const VISION_ROOT_BREADCRUMB: Breadcrumb = {
    key: 'replay-vision',
    name: 'Replay vision',
    path: urls.replayVision(),
    iconType: 'replay_vision',
}

/** A crumb pointing at a saved scanner's page, optionally deep-linked to one of its tabs and its state. */
export function scannerBreadcrumb(
    scannerId: string,
    name?: string | null,
    searchParams?: Record<string, string | number>
): Breadcrumb {
    const path = urls.replayVision(scannerId)
    return {
        key: `scanner-${scannerId}`,
        name: name || 'Scanner',
        // combineUrl with no params returns the path unchanged, so the empty case needs no guard.
        path: combineUrl(path, searchParams ?? {}).url,
    }
}
