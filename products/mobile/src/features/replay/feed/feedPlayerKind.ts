export type FeedPlayerKind = 'web' | 'video'

/**
 * The feed replays recordings in a WebView from their snapshot data, which spends no video exports. Bundling with
 * `EXPO_PUBLIC_REPLAY_FEED_PLAYER=video` selects the MP4 player instead, which renders an export for each new clip.
 */
export const FEED_PLAYER_KIND: FeedPlayerKind = process.env.EXPO_PUBLIC_REPLAY_FEED_PLAYER === 'video' ? 'video' : 'web'
