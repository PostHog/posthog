import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'
import { urls } from 'scenes/urls'

import {
    InvestigationDocument,
    InvestigationEvidence,
    getInvestigationLink,
    removeInvestigationEvidence,
} from './investigationDocument'
import { InvestigationEvidenceQueryActions } from './InvestigationEvidenceQueryActions'
import { InvestigationQueryTask } from './queryAssistantHelpers'

export function InvestigationEvidencePanel({
    document,
    onChange,
    editable,
    selectedId,
    onSelect,
    onAskAI,
}: {
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    editable: boolean
    selectedId: string | null
    onSelect: (id: string | null) => void
    onAskAI?: (task: InvestigationQueryTask, evidenceId: string) => void
}): JSX.Element {
    const fieldId = useId()
    const selected = document.evidence.find((item) => item.id === selectedId) ?? document.evidence[0]
    const update = (patch: Partial<InvestigationEvidence>): void =>
        onChange({
            ...document,
            evidence: document.evidence.map((item) => (item.id === selected.id ? { ...item, ...patch } : item)),
        })
    const add = (): void => {
        const evidence: InvestigationEvidence = {
            id: uuid(),
            reference: document.nextEvidenceNumber,
            title: `Evidence ${document.nextEvidenceNumber}`,
            kind: 'query',
            sql: '',
            url: '',
            note: '',
        }
        onChange({
            ...document,
            evidence: [...document.evidence, evidence],
            nextEvidenceNumber: document.nextEvidenceNumber + 1,
        })
        onSelect(evidence.id)
    }
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-secondary mb-0">
                    Queries are executable evidence. Links connect replays, errors, experiments, and other sources.
                </p>
                {editable && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={add}
                        disabledReason={
                            document.evidence.length >= 12
                                ? 'An investigation supports up to 12 evidence items.'
                                : undefined
                        }
                        data-attr="investigation-add-evidence"
                    >
                        Add evidence
                    </LemonButton>
                )}
            </div>
            {!selected ? (
                <LemonBanner type="info">
                    Add your first piece of evidence. Start with a query that measures the change you want to
                    understand.
                </LemonBanner>
            ) : (
                <div className="grid grid-cols-1 gap-4 @min-[48rem]/investigation:grid-cols-3">
                    <div className="flex flex-col gap-1 min-w-0">
                        {document.evidence.map((item) => (
                            <LemonButton
                                key={item.id}
                                fullWidth
                                active={item.id === selected.id}
                                onClick={() => onSelect(item.id)}
                                data-attr="investigation-select-evidence"
                            >
                                <span className="flex items-center gap-2 min-w-0">
                                    <LemonTag>{`E${item.reference}`}</LemonTag>
                                    <span className="truncate">{item.title || 'Untitled evidence'}</span>
                                </span>
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex flex-col gap-3 min-w-0 @min-[48rem]/investigation:col-span-2">
                        <div className="flex flex-wrap items-end gap-2">
                            <div className="flex-1 min-w-0">
                                <LemonLabel htmlFor={`${fieldId}-title`}>Title</LemonLabel>
                                <LemonInput
                                    id={`${fieldId}-title`}
                                    value={selected.title}
                                    maxLength={200}
                                    disabled={!editable}
                                    onChange={(title) => update({ title })}
                                />
                            </div>
                            <LemonSelect
                                value={selected.kind}
                                disabled={!editable}
                                onChange={(kind) => update({ kind })}
                                options={[
                                    { value: 'query', label: 'SQL query' },
                                    { value: 'link', label: 'Link' },
                                ]}
                            />
                        </div>
                        {selected.kind === 'query' ? (
                            <>
                                <InvestigationEvidenceQueryActions
                                    document={document}
                                    selected={selected}
                                    onAskAI={onAskAI}
                                />
                                <div>
                                    <LemonLabel htmlFor={`${fieldId}-sql`}>SQL</LemonLabel>
                                    <LemonTextArea
                                        id={`${fieldId}-sql`}
                                        className="font-mono"
                                        value={selected.sql}
                                        maxLength={10000}
                                        disabled={!editable}
                                        onChange={(sql) => update({ sql })}
                                        minRows={7}
                                        placeholder="SELECT ..."
                                        data-attr="investigation-evidence-sql"
                                    />
                                </div>
                                <LemonButton
                                    to={urls.sqlEditor({ query: selected.sql })}
                                    targetBlank
                                    size="small"
                                    type="secondary"
                                    disabledReason={!selected.sql.trim() ? 'Enter a query first.' : undefined}
                                >
                                    Explore in SQL editor
                                </LemonButton>
                                <p className="text-xs text-secondary mb-0">
                                    Return a single numeric value for a numeric baseline comparison. Table snapshots
                                    retain up to 50 rows and 20 columns. Use ORDER BY for stable comparisons.
                                </p>
                            </>
                        ) : (
                            <>
                                <div>
                                    <LemonLabel htmlFor={`${fieldId}-url`}>Evidence link</LemonLabel>
                                    <LemonInput
                                        id={`${fieldId}-url`}
                                        value={selected.url}
                                        maxLength={2000}
                                        disabled={!editable}
                                        onChange={(url) => update({ url })}
                                        placeholder="Paste a replay, insight, experiment, or document URL"
                                    />
                                </div>
                                {getInvestigationLink(selected.url) ? (
                                    <LemonButton
                                        to={getInvestigationLink(selected.url)!}
                                        targetBlank
                                        type="secondary"
                                        size="small"
                                    >
                                        Open evidence
                                    </LemonButton>
                                ) : (
                                    selected.url && (
                                        <LemonBanner type="warning">
                                            Use an http or https URL, or a path within PostHog.
                                        </LemonBanner>
                                    )
                                )}
                            </>
                        )}
                        <div>
                            <LemonLabel htmlFor={`${fieldId}-note`}>What this evidence shows</LemonLabel>
                            <LemonTextArea
                                id={`${fieldId}-note`}
                                value={selected.note}
                                maxLength={10000}
                                disabled={!editable}
                                onChange={(note) => update({ note })}
                                minRows={3}
                                placeholder="Explain the result, limitations, and how it relates to the question."
                            />
                        </div>
                        {editable && (
                            <LemonButton
                                status="danger"
                                type="tertiary"
                                size="small"
                                icon={<IconTrash />}
                                onClick={() => onChange(removeInvestigationEvidence(document, selected.id))}
                                data-attr="investigation-remove-evidence"
                            >
                                Remove evidence
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
import { useId } from 'react'
