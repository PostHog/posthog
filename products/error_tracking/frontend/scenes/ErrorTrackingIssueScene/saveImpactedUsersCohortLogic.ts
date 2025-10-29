import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import { errorTrackingIssueEventsQuery } from '../../queries'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import type { saveImpactedUsersCohortLogicType } from './saveImpactedUsersCohortLogicType'

export interface SaveImpactedUsersCohortLogicProps {
    issueId: string
}

export const saveImpactedUsersCohortLogic = kea<saveImpactedUsersCohortLogicType>([
    path((key) => [
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingIssueScene',
        'saveImpactedUsersCohortLogic',
        key,
    ]),
    props({} as SaveImpactedUsersCohortLogicProps),
    key((props) => props.issueId),

    connect((props: SaveImpactedUsersCohortLogicProps) => ({
        values: [
            errorTrackingIssueSceneLogic({ id: props.issueId }),
            ['issueFingerprints', 'filterTestAccounts', 'filterGroup', 'searchQuery', 'dateRange', 'issue'],
        ],
    })),

    actions({
        saveCohort: (cohortName: string) => ({ cohortName }),
        setIsModalOpen: (isOpen: boolean) => ({ isOpen }),
    }),

    loaders({
        cohort: [
            null,
            {
                saveCohort: async ({ cohortName }, breakpoint) => {
                    const { actorsQuery } = saveImpactedUsersCohortLogic.selectors.selectActorsQuery(
                        saveImpactedUsersCohortLogic.findMounted()!.values
                    )

                    if (!actorsQuery) {
                        lemonToast.error('Unable to create cohort: no impacted users found')
                        return null
                    }

                    breakpoint()

                    try {
                        const cohort = await api.create('api/cohort', {
                            is_static: true,
                            name: cohortName,
                            query: actorsQuery,
                        })

                        cohortsModel.actions.cohortCreated(cohort)
                        lemonToast.success('Cohort saved', {
                            toastId: `cohort-saved-${cohort.id}`,
                            button: {
                                label: 'View cohort',
                                action: () => router.actions.push(urls.cohort(cohort.id)),
                            },
                        })

                        return cohort
                    } catch {
                        lemonToast.error('Failed to save cohort')
                        return null
                    }
                },
            },
        ],
    }),

    selectors({
        actorsQuery: [
            (s) => [s.issueFingerprints, s.filterTestAccounts, s.filterGroup, s.searchQuery, s.dateRange],
            (issueFingerprints, filterTestAccounts, filterGroup, searchQuery, dateRange): ActorsQuery | null => {
                if (!issueFingerprints || issueFingerprints.length === 0) {
                    return null
                }

                const eventsQuery = errorTrackingIssueEventsQuery({
                    fingerprints: issueFingerprints.map((f) => f.fingerprint),
                    filterTestAccounts,
                    filterGroup,
                    searchQuery,
                    dateRange,
                    columns: ['person'],
                })

                return setLatestVersionsOnQuery(
                    {
                        kind: NodeKind.ActorsQuery,
                        source: eventsQuery,
                        select: ['actor'],
                        orderBy: [],
                    },
                    { recursion: false }
                )
            },
        ],
    }),

    listeners(({ actions }) => ({
        saveCohortSuccess: () => {
            actions.setIsModalOpen(false)
        },
    })),
])
