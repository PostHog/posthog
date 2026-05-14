import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogReposLogicType } from './gitHogReposLogicType'

export interface GitHogRepository {
    id: number
    name: string
    full_name: string
    owner: string
    integration_id: number
}

export const gitHogReposLogic = kea<gitHogReposLogicType>([
    path(() => ['scenes', 'githog', 'gitHogReposLogic']),
    loaders(() => ({
        repositories: [
            [] as GitHogRepository[],
            {
                loadRepositories: async () => {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get<{ repositories: GitHogRepository[] }>(
                        `api/environments/${getCurrentTeamId()}/githog/`
                    )
                    return response.repositories
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadRepositories()
    }),
])
