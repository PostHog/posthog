import { actions, afterMount, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPullRequestRiskScoreLogicType } from './gitHogPullRequestRiskScoreLogicType'

export interface GitHogPullRequestRiskScoreLogicProps {
    owner: string
    name: string
    number: number
}

export type GitHogRiskLevel = 'low' | 'moderate' | 'high' | 'critical'

export interface GitHogRiskFactor {
    key: string
    label: string
    score: number
    weight: number
    detail: string
}

export interface GitHogRiskScore {
    repository: string
    pr_number: number
    head_sha: string
    base_sha: string
    score: number
    level: GitHogRiskLevel
    headline: string
    rationale: string
    factors: GitHogRiskFactor[]
    truncated: boolean
    cached: boolean
    computed_at: string
}

export const gitHogPullRequestRiskScoreLogic = kea<gitHogPullRequestRiskScoreLogicType>([
    props({} as GitHogPullRequestRiskScoreLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((k) => ['scenes', 'githog', 'gitHogPullRequestRiskScoreLogic', k]),
    actions({
        refreshRiskScore: true,
    }),
    loaders(({ props }) => ({
        riskScore: [
            null as GitHogRiskScore | null,
            {
                loadRiskScore: async ({ refresh }: { refresh?: boolean } = {}) => {
                    const repository = `${props.owner}/${props.name}`
                    const params = new URLSearchParams({
                        repository,
                        number: String(props.number),
                    })
                    if (refresh) {
                        params.set('refresh', 'true')
                    }
                    // nosemgrep: prefer-codegen-api
                    return await api.get<GitHogRiskScore>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_risk_score/?${params.toString()}`
                    )
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        refreshRiskScore: () => {
            actions.loadRiskScore({ refresh: true })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRiskScore({})
    }),
])
