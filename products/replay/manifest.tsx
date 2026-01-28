import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest, RecordingUniversalFilters, ReplayTabs } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Replay',
    urls: {
        replay: (
            tab?: ReplayTabs,
            filters?: Partial<RecordingUniversalFilters>,
            sessionRecordingId?: string,
            order?: string
        ): string =>
            combineUrl(tab ? `/replay/${tab}` : '/replay/home', {
                ...(filters ? { filters } : {}),
                ...(sessionRecordingId ? { sessionRecordingId } : {}),
                ...(order ? { order } : {}),
            }).url,
        replayPlaylist: (id: string): string => `/replay/playlists/${id}`,
        replaySingle: (
            id: string,
            options?: { secondsOffsetFromStart?: number; unixTimestampMillis?: number }
        ): string => {
            if (options?.unixTimestampMillis) {
                return `/replay/${id}?timestamp=${options.unixTimestampMillis}`
            }
            if (options?.secondsOffsetFromStart) {
                return `/replay/${id}?t=${options.secondsOffsetFromStart}`
            }
            return `/replay/${id}`
        },
        replayFilePlayback: (): string => '/replay/file-playback',
        replayKiosk: (): string => '/replay/kiosk',
        replaySettings: (sectionId?: string): string => `/replay/settings${sectionId ? `?sectionId=${sectionId}` : ''}`,
    },
    fileSystemTypes: {
        session_recording_playlist: {
            name: 'Replay playlist',
            iconType: 'session_replay',
            href: (ref: string) => urls.replayPlaylist(ref),
            iconColor: ['var(--color-product-session-replay-light)', 'var(--color-product-session-replay-dark)'],
            filterKey: 'session_recording_playlist',
        },
    },
    treeItemsProducts: [
        {
            path: 'Session replay',
            intents: [ProductKey.SESSION_REPLAY, ProductKey.MOBILE_REPLAY],
            category: 'Behavior',
            href: urls.replay(ReplayTabs.Home),
            type: 'session_recording_playlist',
            iconType: 'session_replay',
            iconColor: ['var(--color-product-session-replay-light)', 'var(--color-product-session-replay-dark)'],
            sceneKey: 'Replay',
            sceneKeys: [
                'Replay',
                'ReplaySingle',
                'ReplaySettings',
                'ReplayPlaylist',
                'ReplayFilePlayback',
                'ReplayKiosk',
            ],
        },
        // TODO: Move over to the `heatmaps` product folder once it exists
        {
            path: 'Heatmaps',
            intents: [ProductKey.HEATMAPS],
            category: 'Behavior',
            iconType: 'heatmap',
            iconColor: ['var(--color-product-heatmaps-light)', 'var(--color-product-heatmaps-dark)'],
            href: urls.heatmaps(),
            tags: ['beta'],
            sceneKey: 'Heatmaps',
            sceneKeys: ['Heatmaps'],
        },
    ],
}
