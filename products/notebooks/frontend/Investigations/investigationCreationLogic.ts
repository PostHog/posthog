import { MakeLogicType, actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { notebooksCreate } from '../generated/api'
import { NotebookApi } from '../generated/api.schemas'
import { newInvestigation } from './investigationDocument'
import { investigationExample } from './investigationExample'

export type InvestigationStarter = 'blank' | 'conversion' | 'example'

export interface investigationCreationLogicValues {
    createdNotebook: NotebookApi | null
    createdNotebookLoading: boolean
}
export interface investigationCreationLogicActions {
    createInvestigation: (starter: InvestigationStarter) => { starter: InvestigationStarter }
    createInvestigationSuccess: (
        createdNotebook: NotebookApi | null,
        payload?: { starter: InvestigationStarter }
    ) => { createdNotebook: NotebookApi | null; payload?: { starter: InvestigationStarter } }
    createInvestigationFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
}
export type investigationCreationLogicType = MakeLogicType<
    investigationCreationLogicValues,
    investigationCreationLogicActions
>

export const investigationCreationLogic = kea<investigationCreationLogicType>([
    path(['products', 'notebooks', 'investigations', 'investigationCreationLogic']),
    actions({ createInvestigation: (starter: InvestigationStarter) => ({ starter }) }),
    loaders(({ values }) => ({
        createdNotebook: [
            null as NotebookApi | null,
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
                    const markdown = serializeMarkdownNotebook({
                        type: 'doc',
                        errors: [],
                        nodes: [
                            {
                                type: 'component',
                                id: 'investigation',
                                tagName: 'Investigation',
                                props: { nodeId: 'investigation', document },
                            },
                        ],
                    })
                    const notebook = await notebooksCreate(String(teamLogic.values.currentTeamId), {
                        title:
                            starter === 'example'
                                ? 'Example investigation: trial conversion'
                                : document.question || 'Untitled investigation',
                        content: buildMarkdownNotebookContent(markdown),
                    })
                    posthog.capture('notebook investigation created', { starter })
                    router.actions.push(urls.notebook(notebook.short_id))
                    return notebook ?? values.createdNotebook
                },
            },
        ],
    })),
])
