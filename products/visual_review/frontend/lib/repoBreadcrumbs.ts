import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { splitRepoFullName } from './repoPaths'

/** The crumbs every repository page shares, so the top bar reads the same on detail pages as on tabs. */
export function repoBreadcrumbs(repoFullName: string | null): Breadcrumb[] {
    if (!repoFullName) {
        return [
            { key: 'visual_review', name: 'Visual review', path: urls.visualReviewRuns(), iconType: 'visual_review' },
        ]
    }
    return [
        {
            key: 'visual_review',
            name: 'Visual review',
            path: urls.visualReviewRepoRuns(...splitRepoFullName(repoFullName)),
            iconType: 'visual_review',
        },
        { key: ['visual_review_repo', repoFullName], name: repoFullName, iconType: 'visual_review' },
    ]
}
