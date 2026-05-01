import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { visualReviewReposList, visualReviewReposRetrieve } from '../generated/api'
import type { RepoApi } from '../generated/api.schemas'
import type { visualReviewRepoLogicType } from './visualReviewRepoLogicType'

export interface VisualReviewRepoLogicProps {
    repoId: string
}

// Shared repo state for both Runs and Snapshots scenes — keyed by repoId so
// the data only loads once per workspace and survives tab navigation. Without
// this, each scene's own loadRepo re-fetches on mount and the title/tab
// strip flicker as the response comes back.
export const visualReviewRepoLogic = kea<visualReviewRepoLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewRepoLogic']),
    props({} as VisualReviewRepoLogicProps),
    key((props) => props.repoId),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    loaders(({ props, values }) => ({
        repo: [
            null as RepoApi | null,
            {
                loadRepo: async () => {
                    return visualReviewReposRetrieve(String(values.currentProjectId), props.repoId)
                },
            },
        ],
        // Sibling repos surface in the title-bar dropdown so a multi-repo
        // workspace can switch with a single click. Loaded lazily — single-
        // repo workspaces never render the dropdown, but the request is cheap.
        allRepos: [
            [] as RepoApi[],
            {
                loadAllRepos: async () => {
                    const response = await visualReviewReposList(String(values.currentProjectId))
                    return response.results ?? []
                },
            },
        ],
    })),
    selectors({
        repoFullName: [(s) => [s.repo], (repo: RepoApi | null): string | undefined => repo?.repo_full_name],
        otherRepos: [
            (s) => [s.allRepos, (_, p) => p.repoId],
            (allRepos: RepoApi[], repoId: string): RepoApi[] => allRepos.filter((r) => r.id !== repoId),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRepo()
        actions.loadAllRepos()
    }),
])
