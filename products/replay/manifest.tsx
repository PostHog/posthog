import { IconRewindPlay } from '@posthog/icons'
import { combineUrl } from 'kea-router'
import { urls } from 'scenes/urls'

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
        replaySingle: (id: string): string => `/replay/${id}`,
        replayFilePlayback: (): string => '/replay/file-playback',
        replaySettings: (sectionId?: string): string => `/replay/settings${sectionId ? `?sectionId=${sectionId}` : ''}`,
    },
    fileSystemTypes: {
        session_recording_playlist: {
            icon: <IconRewindPlay />,
            href: (ref: string) => urls.replayPlaylist(ref),
        },
    },
    treeItemsNew: [
        {
            path: `Replay playlist`,
            type: 'session_recording_playlist',
            href: urls.replayPlaylist('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: 'Session replay',
            href: urls.replay(ReplayTabs.Home),
            type: 'session_recording_playlist',
        },
    ],
    fileSystemFilterTypes: {
        session_recording_playlist: { name: 'Replay playlists' },
    },
}
