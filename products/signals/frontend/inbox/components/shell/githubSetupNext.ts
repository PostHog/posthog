import { combineUrl } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

/**
 * Build the GitHub OAuth `next` for the setup modal. The round trip has to return to wherever the user
 * started, with `setup=github` so the modal reopens showing the result. `GithubIntegration` adds the
 * `/project/<id>` prefix itself, so strip it here – `location.pathname` already carries the prefix and
 * would otherwise be doubled into a dead route.
 */
export function buildGithubSetupNext(pathname: string, searchParams: Record<string, any>): string {
    return combineUrl(removeProjectIdIfPresent(pathname), { ...searchParams, setup: 'github' }).url
}
