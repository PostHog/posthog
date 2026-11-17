import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { uuid } from 'lib/utils/dom'

import { aiShellLogic } from '~/layout/ai/aiShellLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { InvestigationDocument, investigationDocumentSchema } from './investigationDocument'
import { investigationQuerySessionLogic } from './investigationQuerySessionLogic'
import {
    INVESTIGATION_QUERY_TASKS,
    InvestigationQueryProposal,
    InvestigationQueryRequest,
    InvestigationQueryTask,
    proposalReplacementReason,
    applyQueryProposal,
    queryProposalError,
} from './queryAssistantHelpers'

export interface InvestigationQueryAssistantProps {
    scope: string
    document: InvestigationDocument
    editable: boolean
    onChange: (document: InvestigationDocument) => void
    onSelect: (id: string) => void
}

export interface investigationQueryAssistantLogicValues {
    activeRequestId: string | null
    prompt: string
    task: InvestigationQueryTask
    targetId: string | null
    request: InvestigationQueryRequest | null
    proposal: InvestigationQueryProposal | null
    error: string | null
}
export interface investigationQueryAssistantLogicActions {
    activateRequest: (id: string) => { id: string }
    setPhaiViewMode: (mode: 'new' | 'legacy') => { mode: 'new' | 'legacy' }
    openSidePanel: (tab: SidePanelTab, options?: string) => { tab: SidePanelTab; options: string | undefined }
    setPrompt: (prompt: string) => { prompt: string }
    setTask: (task: InvestigationQueryTask) => { task: InvestigationQueryTask }
    setTargetId: (targetId: string | null) => { targetId: string | null }
    setRequest: (request: InvestigationQueryRequest | null) => { request: InvestigationQueryRequest | null }
    setProposal: (proposal: InvestigationQueryProposal | null) => { proposal: InvestigationQueryProposal | null }
    setError: (error: string | null) => { error: string | null }
    askAssistant: () => { value: true }
    receiveProposal: (input: Record<string, unknown> | null) => { input: Record<string, unknown> | null }
    acceptProposal: (mode: 'replace' | 'add') => { mode: 'replace' | 'add' }
    dismissProposal: () => { value: true }
}
export type investigationQueryAssistantLogicType = MakeLogicType<
    investigationQueryAssistantLogicValues,
    investigationQueryAssistantLogicActions,
    InvestigationQueryAssistantProps
>

export const investigationQueryAssistantLogic = kea<investigationQueryAssistantLogicType>([
    props({} as InvestigationQueryAssistantProps),
    key(({ scope }) => scope),
    path((key) => ['products', 'notebooks', 'investigations', 'investigationQueryAssistantLogic', key]),
    connect({
        values: [investigationQuerySessionLogic, ['activeRequestId']],
        actions: [
            aiShellLogic,
            ['setPhaiViewMode'],
            sidePanelStateLogic,
            ['openSidePanel'],
            investigationQuerySessionLogic,
            ['activateRequest'],
        ],
    }),
    actions({
        setPrompt: (prompt: string) => ({ prompt }),
        setTask: (task: InvestigationQueryTask) => ({ task }),
        setTargetId: (targetId: string | null) => ({ targetId }),
        setRequest: (request: InvestigationQueryRequest | null) => ({ request }),
        setProposal: (proposal: InvestigationQueryProposal | null) => ({ proposal }),
        setError: (error: string | null) => ({ error }),
        askAssistant: true,
        receiveProposal: (input: Record<string, unknown> | null) => ({ input }),
        acceptProposal: (mode: 'replace' | 'add') => ({ mode }),
        dismissProposal: true,
    }),
    reducers({
        prompt: ['', { setPrompt: (_, { prompt }) => prompt.slice(0, 2000) }],
        task: ['write' as InvestigationQueryTask, { setTask: (_, { task }) => task }],
        targetId: [null as string | null, { setTargetId: (_, { targetId }) => targetId }],
        request: [null as InvestigationQueryRequest | null, { setRequest: (_, { request }) => request }],
        proposal: [null as InvestigationQueryProposal | null, { setProposal: (_, { proposal }) => proposal }],
        error: [null as string | null, { setError: (_, { error }) => error }],
    }),
    listeners(({ actions, values, props }) => ({
        askAssistant: () => {
            if (!props.editable) {
                return
            }
            const target = props.document.evidence.find((item) => item.id === values.targetId && item.kind === 'query')
            if (['fix', 'explain'].includes(values.task) && !target) {
                actions.setError('Select a query to explain or fix.')
                return
            }
            if (!values.prompt.trim() && !props.document.question.trim() && !target) {
                actions.setError('Describe what you want to measure, or enter an investigation question first.')
                return
            }
            const id = uuid()
            actions.activateRequest(id)
            actions.setRequest({
                id,
                task: values.task,
                targetId: target?.id ?? null,
                originalSql: target?.sql ?? null,
                prompt: values.prompt,
            })
            actions.setProposal(null)
            actions.setError(null)
            actions.setPhaiViewMode('new')
            actions.openSidePanel(SidePanelTab.Max, INVESTIGATION_QUERY_TASKS[values.task].prompt)
            // Pinned analytics names: changing these splits the query-assistant funnel.
            posthog.capture('notebook investigation query assistant opened', {
                task: values.task,
                has_target: !!target,
            })
        },
        receiveProposal: ({ input }) => {
            const { request } = values
            if (!props.editable || !request || request.task === 'explain' || typeof input?.context !== 'string') {
                return
            }
            if (!input.context.includes(`[investigation-query:${request.id}]`)) {
                return
            }
            if (request.id !== values.activeRequestId) {
                return
            }
            actions.setProposal(null)
            const error = queryProposalError(input)
            if (error) {
                actions.setError(error)
                return
            }
            actions.setProposal({ requestId: request.id, sql: input.query as string })
            actions.setError(null)
            posthog.capture('notebook investigation query proposed', { task: request.task })
        },
        acceptProposal: ({ mode }) => {
            const { proposal, request } = values
            if (!props.editable || !proposal || !request || proposal.requestId !== request.id) {
                return
            }
            const target = props.document.evidence.find((item) => item.id === request.targetId)
            const reason =
                mode === 'replace'
                    ? proposalReplacementReason(target, request)
                    : props.document.evidence.length >= 12
                      ? 'An investigation supports up to 12 evidence items.'
                      : undefined
            if (reason) {
                actions.setError(reason)
                return
            }
            const { document, evidenceId } = applyQueryProposal(props.document, request, proposal, mode)
            if (!investigationDocumentSchema.safeParse(document).success || JSON.stringify(document).length > 500_000) {
                actions.setError(
                    'This investigation is too large to save the query. Remove older evidence or shorten the text first.'
                )
                return
            }
            props.onChange(document)
            props.onSelect(evidenceId)
            actions.setProposal(null)
            actions.setRequest(null)
            actions.setError(null)
            posthog.capture('notebook investigation query accepted', { task: request.task, mode })
        },
        dismissProposal: () => {
            actions.setProposal(null)
            actions.setRequest(null)
            actions.setError(null)
            posthog.capture('notebook investigation query dismissed')
        },
    })),
])
