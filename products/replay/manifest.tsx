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
    },
    fileSystemTypes: {},
    treeItems: [
        {
            path: 'Explore/Recordings/Recordings',
            href: () => urls.replay(ReplayTabs.Home),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Recordings/What to watch',
            href: () => urls.replay(ReplayTabs.Templates),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Recordings/Playlists',
            href: () => urls.replay(ReplayTabs.Playlists),
            icon: <IconRewindPlay />,
        },
    ],
}
