/**
 * Product manifest for stamphog.
 *
 * The auto-approval UI renders inside the Code review scene of review_hog, so this manifest owns no
 * scene. It keeps the GitHub App callback route and forwards the old /stamphog pages.
 */
import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Stamphog',
    activityDescribers: {
        [ActivityScope.STAMPHOG_REPO_CONFIG]: () =>
            import('./frontend/activityDescriber').then((module) => module.stamphogRepoConfigActivityDescriber),
    },
    scenes: {},
    routes: {
        // The Setup URL of the Stamphog GitHub App points here, so the path must not change. GitHub sends
        // the user back with an installation_id and a code, and the Approval settings tab of Code review
        // finishes the connection. It lives under /stamphog, not /integrations/*, so the generic
        // /integrations/:kind/callback scene route can't shadow it (product routes register after core).
        '/stamphog/install/callback': ['CodeReview', 'stamphogCallback'],
    },
    // Bookmarks and older links point at the retired /stamphog pages, so each one forwards to its tab and
    // keeps its search params. The runs and team view filters use the same param names in both places.
    // The digest list opens as the digest history over Approval settings, so its page param gets its own
    // name there.
    redirects: {
        '/stamphog': (_params, searchParams, hashParams): string =>
            combineUrl(urls.codeReview(), { ...searchParams, tab: 'approval_settings' }, hashParams).url,
        '/stamphog/runs': (_params, searchParams, hashParams): string =>
            combineUrl(urls.codeReview(), { ...searchParams, tab: 'approval_history' }, hashParams).url,
        '/stamphog/area': (_params, searchParams, hashParams): string =>
            combineUrl(urls.codeReview(), { ...searchParams, tab: 'code_you_own' }, hashParams).url,
        '/stamphog/digests': (_params, { page, ...searchParams }, hashParams): string =>
            combineUrl(
                urls.codeReview(),
                { ...searchParams, tab: 'approval_settings', digests: '1', digests_page: page },
                hashParams
            ).url,
    },
    urls: {
        stamphogCallback: (): string => '/stamphog/install/callback',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
