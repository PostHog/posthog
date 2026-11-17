import { MakeLogicType, actions, getContext, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { uuid } from 'lib/utils/dom'

import { performQuery } from '~/queries/query'
import { HogQLQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import {
    InvestigationDocument,
    InvestigationEvidence,
    InvestigationResult,
    appendInvestigationRun,
    investigationDocumentSchema,
    snapshotInvestigationResult,
} from './investigationDocument'

export interface InvestigationLogicProps {
    scope: string
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    editable: boolean
}

export type InvestigationTab = 'overview' | 'evidence' | 'hypotheses' | 'history' | 'report'

export interface investigationLogicValues {
    document: InvestigationDocument
    tab: InvestigationTab
    running: boolean
    completed: number
    error: string | null
    selectedEvidenceId: string | null
}

export interface investigationLogicActions {
    replaceDocument: (document: InvestigationDocument) => { document: InvestigationDocument }
    changeDocument: (document: InvestigationDocument) => { document: InvestigationDocument }
    setTab: (tab: InvestigationTab) => { tab: InvestigationTab }
    setSelectedEvidenceId: (id: string | null) => { id: string | null }
    setRunning: (running: boolean) => { running: boolean }
    setCompleted: (completed: number) => { completed: number }
    setError: (error: string | null) => { error: string | null }
    runEvidence: () => { value: true }
    cancelRun: () => { value: true }
}

export type investigationLogicType = MakeLogicType<
    investigationLogicValues,
    investigationLogicActions,
    InvestigationLogicProps
>

export const investigationLogic = kea<investigationLogicType>([
    props({} as InvestigationLogicProps),
    key(({ scope }) => scope),
    path((key) => ['products', 'notebooks', 'investigations', 'investigationLogic', key]),
    actions({
        replaceDocument: (document: InvestigationDocument) => ({ document }),
        changeDocument: (document: InvestigationDocument) => ({ document }),
        setTab: (tab: InvestigationTab) => ({ tab }),
        setSelectedEvidenceId: (id: string | null) => ({ id }),
        setRunning: (running: boolean) => ({ running }),
        setCompleted: (completed: number) => ({ completed }),
        setError: (error: string | null) => ({ error }),
        runEvidence: true,
        cancelRun: true,
    }),
    reducers(({ props }) => ({
        document: [props.document, { replaceDocument: (_, { document }) => document }],
        tab: ['overview' as InvestigationTab, { setTab: (_, { tab }) => tab }],
        running: [false, { setRunning: (_, { running }) => running }],
        completed: [0, { setCompleted: (_, { completed }) => completed }],
        error: [null as string | null, { setError: (_, { error }) => error }],
        selectedEvidenceId: [null as string | null, { setSelectedEvidenceId: (_, { id }) => id }],
    })),
    listeners(({ actions, values, props, cache }) => ({
        changeDocument: ({ document }) => {
            if (!props.editable) {
                return
            }
            const parsed = investigationDocumentSchema.safeParse(document)
            if (!parsed.success || JSON.stringify(document).length > 500_000) {
                actions.setError(
                    'This investigation is too large or contains invalid values. Shorten the text or remove evidence and try again.'
                )
                return
            }
            actions.replaceDocument(parsed.data)
            props.onChange(parsed.data)
        },
        runEvidence: async (_, breakpoint) => {
            if (!props.editable || values.running) {
                return
            }
            const evidence = values.document.evidence.filter((item) => item.kind === 'query' && item.sql.trim())
            if (!evidence.length) {
                actions.setTab('evidence')
                actions.setError('Add a SQL query to your evidence before running the investigation.')
                return
            }
            actions.setRunning(true)
            actions.setCompleted(0)
            actions.setError(null)
            const controller = new AbortController()
            const mountedIn = getContext()
            const disposables = cache.disposables
            disposables.add(() => () => controller.abort(), 'investigation-run', { pauseOnPageHidden: false })
            const results: InvestigationResult[] = []
            const conclusion = values.document.conclusion
            // Pinned analytics names: changing these splits investigation funnels.
            posthog.capture('notebook investigation run started', { query_count: evidence.length })
            try {
                for (const item of evidence) {
                    try {
                        const result = await executeInvestigationEvidence(item, controller.signal)
                        breakpoint()
                        if (controller.signal.aborted) {
                            return
                        }
                        results.push(result)
                    } catch (error) {
                        breakpoint()
                        if (controller.signal.aborted) {
                            return
                        }
                        results.push(failedResult(item, error))
                    }
                    actions.setCompleted(results.length)
                }
                actions.changeDocument(
                    appendInvestigationRun(values.document, {
                        id: uuid(),
                        at: new Date().toISOString(),
                        conclusion,
                        results,
                    })
                )
                actions.setTab('history')
                posthog.capture('notebook investigation run finished', {
                    query_count: results.length,
                    failed_count: results.filter((result) => result.error).length,
                })
            } finally {
                if (!disposables.isDisposed && getContext() === mountedIn) {
                    actions.setRunning(false)
                    disposables.dispose('investigation-run')
                }
            }
        },
        cancelRun: () => {
            cache.disposables.dispose('investigation-run')
        },
        setTab: ({ tab }) => {
            posthog.capture('notebook investigation tab opened', { tab })
        },
    })),
    propsChanged(({ actions, props }, previous) => {
        if (props.document !== previous.document) {
            actions.replaceDocument(props.document)
        }
    }),
])

function failedResult(evidence: InvestigationEvidence, error: unknown): InvestigationResult {
    const message =
        error instanceof ApiError
            ? error.detail || error.message
            : error instanceof Error
              ? error.message
              : 'Query failed. Review the SQL and run again.'
    return {
        evidenceId: evidence.id,
        title: evidence.title,
        sql: evidence.sql,
        columns: [],
        rows: [],
        truncated: false,
        error: message.slice(0, 2000),
    }
}

async function executeInvestigationEvidence(
    evidence: InvestigationEvidence,
    signal: AbortSignal
): Promise<InvestigationResult> {
    const response = await performQuery<HogQLQuery>(
        {
            kind: NodeKind.HogQLQuery,
            query: evidence.sql,
            tags: { productKey: ProductKey.NOTEBOOKS, name: 'investigation_evidence' },
        },
        { signal: signal, queryTelemetry: 'metadata' },
        'force_async'
    )

    return snapshotInvestigationResult(evidence, response.columns ?? [], response.results ?? [], response.hasMore)
}
