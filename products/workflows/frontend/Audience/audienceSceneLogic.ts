// pinned: URL path segments under /audience, renaming breaks bookmarks
export const AUDIENCE_TABS = ['topics', 'suppression'] as const
export type AudienceTab = (typeof AUDIENCE_TABS)[number]
