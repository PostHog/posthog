import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRDiffLogicType } from './gitHogPRDiffLogicType'

export interface GitHogPRDiffLogicProps {
    owner: string
    name: string
    number: number | string
}

interface PRDiffResponse {
    repository: string
    pr_number: number
    diff: string
}

export const gitHogPRDiffLogic = kea<gitHogPRDiffLogicType>([
    props({} as GitHogPRDiffLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((prKey) => ['scenes', 'githog', 'gitHogPRDiffLogic', prKey]),
    loaders(({ props }) => ({
        diff: [
            '' as string,
            {
                loadDiff: async () => {
                    const repository = `${props.owner}/${props.name}`
                    const params = new URLSearchParams({
                        repository,
                        pr_number: String(props.number),
                    })
                    const response = await api.get<PRDiffResponse>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_diff/?${params.toString()}`
                    )
                    return response.diff
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadDiff()
    }),
])
