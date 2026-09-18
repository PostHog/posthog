/**
 * URL of the frame illustrating a Replay Vision observation. Built here rather than imported from that
 * product's generated client, because products don't import each other and a URL is the contract they
 * share. Pinned: the route is Replay Vision's public API.
 */
export function observationThumbnailUrl(teamId: number, observationId: string): string {
    return `/api/projects/${teamId}/vision/observations/${observationId}/thumbnail/`
}
