import { useContext, useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { NotebookComponentRenderProps } from 'lib/components/MarkdownNotebook/types'
import { MarkdownNotebookRuntimeContext } from 'scenes/notebooks/Notebook/markdownNotebookRuntime'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { InvestigationAssistantButton } from './InvestigationAssistantButton'
import { investigationDocumentSchema, newInvestigation } from './investigationDocument'
import { InvestigationWorkspace } from './InvestigationWorkspace'

export function NotebookInvestigation({ node, notebookMode, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const runtime = useContext(MarkdownNotebookRuntimeContext)
    const parsed = useMemo(
        () => investigationDocumentSchema.safeParse(node.props.document ?? newInvestigation()),
        [node.props.document]
    )
    useAttachedContext(
        runtime?.notebookShortId && notebookMode === 'edit'
            ? [
                  { type: 'notebook', key: runtime.notebookShortId, label: runtime.notebookTitle },
                  {
                      type: 'instructions',
                      hidden: true,
                      value: 'This notebook contains an Investigation component. Read it with notebooks-get. Help investigate its question by validating metric definitions, cohort maturity, tracking, and comparable populations before proposing explanations. Use actual queries and cite the evidence. Distinguish association from causality and individual replays from prevalence. Record uncertainty and competing explanations. Never invent query results or mark a premise check verified without evidence. The Investigation document prop holds question, context, checks, evidence, hypotheses, conclusion, decision, followUp, runs, and baselineId. Preserve run snapshots and IDs when editing. When an investigation_query_editor item is attached, follow its query review workflow and do not edit the notebook directly. Otherwise, prefer adding ordinary notebook query and evidence cells using notebooks-add-cell for deeper analysis. The user can run the investigation evidence queries to save new snapshots.',
                  },
              ]
            : null
    )
    if (!parsed.success) {
        return (
            <LemonBanner type="error">
                This investigation contains an unsupported or invalid document. Review the notebook source or restore a
                previous version from history. Your saved content has not been replaced.
            </LemonBanner>
        )
    }
    return (
        <InvestigationWorkspace
            scope={`${runtime?.notebookShortId ?? 'preview'}:${String(node.props.nodeId ?? node.id)}`}
            document={parsed.data}
            editable={notebookMode === 'edit'}
            assistant={<InvestigationAssistantButton />}
            onChange={(document) => updateProps({ document })}
        />
    )
}
