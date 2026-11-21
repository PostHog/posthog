import { MakeLogicType, actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { investigationsCreate } from './generated/api'
import { SavedInvestigationApi } from './generated/api.schemas'
import { newInvestigation } from './investigationDocument'
import { investigationExample } from './investigationExample'

export type InvestigationStarter = 'blank' | 'conversion' | 'example'

export interface investigationCreationLogicValues {
    createdInvestigation: SavedInvestigationApi | null
    createdInvestigationLoading: boolean
}
export interface investigationCreationLogicActions {
    createInvestigation: (starter: InvestigationStarter) => { starter: InvestigationStarter }
    createInvestigationSuccess: (
        createdInvestigation: SavedInvestigationApi | null,
        payload?: { starter: InvestigationStarter }
    ) => { createdInvestigation: SavedInvestigationApi | null; payload?: { starter: InvestigationStarter } }
    createInvestigationFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
}
export type investigationCreationLogicType = MakeLogicType<
    investigationCreationLogicValues,
    investigationCreationLogicActions
>

export const investigationCreationLogic = kea<investigationCreationLogicType>([
    path(['products', 'investigations', 'investigationCreationLogic']),
    actions({ createInvestigation: (starter: InvestigationStarter) => ({ starter }) }),
    loaders(({ values }) => ({
        createdInvestigation: [
            null as SavedInvestigationApi | null,
            {
                createInvestigation: async ({ starter }: { starter: InvestigationStarter }) => {
                    const document =
                        starter === 'example'
                            ? investigationExample()
                            : newInvestigation(starter === 'conversion' ? 'Why did conversion change?' : '')
                    if (starter === 'conversion') {
                        document.context =
                            'Define your entry event, conversion event, conversion window, and the two periods you want to compare. Exclude incomplete cohorts.'
                        document.hypotheses = [
                            {
                                id: 'population',
                                title: 'The population or acquisition mix changed',
                                status: 'open',
                                reasoning: '',
                                evidenceIds: [],
                            },
                            {
                                id: 'experience',
                                title: 'The product experience changed',
                                status: 'open',
                                reasoning: '',
                                evidenceIds: [],
                            },
                            {
                                id: 'measurement',
                                title: 'Tracking or data freshness changed',
                                status: 'open',
                                reasoning: '',
                                evidenceIds: [],
                            },
                        ]
                    }
                    const investigation = await investigationsCreate(String(teamLogic.values.currentTeamId), {
                        document,
                    })
                    posthog.capture('notebook investigation created', { starter })
                    router.actions.push(urls.investigation(investigation.id))
                    return investigation ?? values.createdInvestigation
                },
            },
        ],
    })),
])
