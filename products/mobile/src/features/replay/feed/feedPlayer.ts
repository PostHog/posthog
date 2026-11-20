import type { VideoPlayer } from 'expo-video'

import type { ReplayVideoSource } from '@/api/replayVideo'

import type { WebReplayPlayer } from '../web/WebReplayPlayer'

/** The part of `expo-video`'s player a feed card drives. The WebView replay player implements the same surface. */
export type FeedPlayer = Pick<
    VideoPlayer,
    'status' | 'currentTime' | 'playbackRate' | 'playing' | 'play' | 'pause' | 'addListener'
>

export type PoolPlayer =
    | { kind: 'video'; player: VideoPlayer; key: string; source: ReplayVideoSource; loaded: boolean; failed: boolean }
    | { kind: 'web'; player: WebReplayPlayer; key: string; loaded: boolean }
