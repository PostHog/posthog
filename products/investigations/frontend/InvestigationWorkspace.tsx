import { useActions, useValues } from 'kea'

import { IconPlay, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { aiShellLogic } from '~/layout/ai/aiShellLogic'

import { InvestigationEvidencePanel } from './InvestigationEvidencePanel'
import { InvestigationHistory } from './InvestigationHistory'
import { InvestigationHypotheses } from './InvestigationHypotheses'
import { InvestigationLogicProps, investigationLogic } from './investigationLogic'
import { InvestigationOverview } from './InvestigationOverview'
import { InvestigationQueryAssistant } from './InvestigationQueryAssistant'
import { investigationQueryAssistantLogic } from './investigationQueryAssistantLogic'
import { InvestigationReport } from './InvestigationReport'

export function InvestigationWorkspace(props: InvestigationLogicProps): JSX.Element {
    const logic = investigationLogic(props)
    const { document, tab, running, completed, error, selectedEvidenceId } = useValues(logic)
    const { changeDocument, setTab, runEvidence, cancelRun, setError, setSelectedEvidenceId } = useActions(logic)
    const queryCount = document.evidence.filter((item) => item.kind === 'query' && item.sql.trim()).length
    const panelProps = { document, onChange: changeDocument, editable: props.editable }
    const { isMaxAvailable, isPhaiSandboxFlagOn } = useValues(aiShellLogic)
    const canUseAssistant = props.editable && isMaxAvailable && isPhaiSandboxFlagOn
    const assistantProps = {
        scope: props.scope,
        ...panelProps,
        onSelect: (id: string) => {
            setSelectedEvidenceId(id)
            setTab('evidence')
        },
    }
    const { setTask, setTargetId, setPrompt, askAssistant } = useActions(
        investigationQueryAssistantLogic(assistantProps)
    )
    return (
        <section
            className="@container/investigation min-w-0"
            aria-label="Investigation workspace"
            data-attr="investigation-workspace"
        >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
                <div className="flex flex-col gap-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-base m-0">Evidence workspace</h2>
                        <LemonTag type="highlight">Beta</LemonTag>
                        {!props.editable && <LemonTag>Read only</LemonTag>}
                    </div>
                    <span className="text-secondary text-sm">
                        Connect a question, its evidence, and what you decide to do.
                    </span>
                </div>
                {props.editable && (
                    <div className="flex flex-wrap gap-2 items-center">
                        {running && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconX />}
                                onClick={cancelRun}
                                data-attr="investigation-cancel-run"
                            >
                                Cancel
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlay />}
                            loading={running}
                            onClick={runEvidence}
                            data-attr="investigation-run-evidence"
                        >
                            {running ? `Running ${completed}/${queryCount}` : 'Run evidence'}
                        </LemonButton>
                    </div>
                )}
            </div>
            {document.example && (
                <LemonBanner type="info" className="mt-4">
                    This example uses invented data. Its SQL returns fixed example values and does not query your
                    product events. Replace the queries to investigate your own data.
                </LemonBanner>
            )}
            {error && (
                <LemonBanner type="error" className="mt-4" onClose={() => setError(null)}>
                    {error}
                </LemonBanner>
            )}
            <div
                className={
                    canUseAssistant
                        ? 'grid gap-6 @min-[64rem]/investigation:grid-cols-[minmax(0,1fr)_20rem]'
                        : 'min-w-0'
                }
            >
                <div className="min-w-0">
                    <LemonTabs
                        activeKey={tab}
                        onChange={setTab}
                        tabs={[
                            { key: 'overview', label: 'Overview', content: <InvestigationOverview {...panelProps} /> },
                            {
                                key: 'evidence',
                                label: `Evidence (${document.evidence.length})`,
                                content: (
                                    <InvestigationEvidencePanel
                                        {...panelProps}
                                        selectedId={selectedEvidenceId}
                                        onSelect={setSelectedEvidenceId}
                                        onAskAI={
                                            canUseAssistant
                                                ? (task, id) => {
                                                      setTask(task)
                                                      setTargetId(id)
                                                      setPrompt('')
                                                      askAssistant()
                                                  }
                                                : undefined
                                        }
                                    />
                                ),
                            },
                            {
                                key: 'hypotheses',
                                label: `Hypotheses (${document.hypotheses.length})`,
                                content: <InvestigationHypotheses {...panelProps} />,
                            },
                            {
                                key: 'history',
                                label: `Runs (${document.runs.length})`,
                                content: <InvestigationHistory {...panelProps} />,
                            },
                            { key: 'report', label: 'Report', content: <InvestigationReport {...panelProps} /> },
                        ]}
                    />
                </div>
                {canUseAssistant && (
                    <aside className="min-w-0 pt-4" aria-label="Query assistance">
                        <LemonCollapse
                            defaultActiveKey="assistant"
                            panels={[
                                {
                                    key: 'assistant',
                                    header: 'Query assistance',
                                    content: <InvestigationQueryAssistant {...assistantProps} />,
                                },
                            ]}
                        />
                    </aside>
                )}
            </div>
        </section>
    )
}
