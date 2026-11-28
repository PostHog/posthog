import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { uuid } from 'lib/utils/dom'

import { InvestigationDocument, InvestigationHypothesis } from './investigationDocument'

export function InvestigationHypotheses({
    document,
    onChange,
    editable,
}: {
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    editable: boolean
}): JSX.Element {
    const fieldId = useId()
    const update = (id: string, patch: Partial<InvestigationHypothesis>): void =>
        onChange({
            ...document,
            hypotheses: document.hypotheses.map((item) => (item.id === id ? { ...item, ...patch } : item)),
        })
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-secondary mb-0">Keep competing explanations and the evidence for each one.</p>
                {editable && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        disabledReason={
                            document.hypotheses.length >= 12
                                ? 'An investigation supports up to 12 hypotheses.'
                                : undefined
                        }
                        onClick={() =>
                            onChange({
                                ...document,
                                hypotheses: [
                                    ...document.hypotheses,
                                    { id: uuid(), title: '', status: 'open', reasoning: '', evidenceIds: [] },
                                ],
                            })
                        }
                        data-attr="investigation-add-hypothesis"
                    >
                        Add hypothesis
                    </LemonButton>
                )}
            </div>
            {!document.hypotheses.length && (
                <LemonBanner type="info">
                    Start with an explanation you can test. For example, a change in the mix of new users could explain
                    a conversion drop.
                </LemonBanner>
            )}
            {document.hypotheses.map((item, index) => (
                <LemonCard key={item.id} hoverEffect={false} className="p-4">
                    <div className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-end gap-2">
                            <div className="flex-1 min-w-0">
                                <LemonLabel htmlFor={`${fieldId}-${item.id}`}>{`Hypothesis ${index + 1}`}</LemonLabel>
                                <LemonInput
                                    id={`${fieldId}-${item.id}`}
                                    value={item.title}
                                    maxLength={500}
                                    disabled={!editable}
                                    onChange={(title) => update(item.id, { title })}
                                    placeholder="What could explain the change?"
                                />
                            </div>
                            <LemonSelect
                                value={item.status}
                                disabled={!editable}
                                onChange={(status) => update(item.id, { status })}
                                options={[
                                    { value: 'open', label: 'Open' },
                                    { value: 'supported', label: 'Supported' },
                                    { value: 'ruled_out', label: 'Ruled out' },
                                ]}
                            />
                        </div>
                        <LemonTextArea
                            value={item.reasoning}
                            maxLength={10000}
                            disabled={!editable}
                            onChange={(reasoning) => update(item.id, { reasoning })}
                            placeholder="What supports or contradicts this explanation? What would change your mind?"
                            minRows={3}
                            aria-label={`Reasoning for hypothesis ${index + 1}`}
                        />
                        <div className="flex flex-wrap gap-3">
                            {document.evidence.map((evidence) => (
                                <LemonCheckbox
                                    key={evidence.id}
                                    label={`E${evidence.reference}: ${evidence.title}`}
                                    checked={item.evidenceIds.includes(evidence.id)}
                                    disabled={!editable}
                                    onChange={(checked) =>
                                        update(item.id, {
                                            evidenceIds: checked
                                                ? [...item.evidenceIds, evidence.id]
                                                : item.evidenceIds.filter((id) => id !== evidence.id),
                                        })
                                    }
                                />
                            ))}
                        </div>
                        {item.status !== 'open' && (!item.reasoning.trim() || !item.evidenceIds.length) && (
                            <LemonBanner type="warning">
                                Add reasoning and link evidence so another person can review this assessment.
                            </LemonBanner>
                        )}
                        {editable && (
                            <LemonButton
                                type="tertiary"
                                status="danger"
                                size="small"
                                icon={<IconTrash />}
                                onClick={() =>
                                    onChange({
                                        ...document,
                                        hypotheses: document.hypotheses.filter(
                                            (hypothesis) => hypothesis.id !== item.id
                                        ),
                                    })
                                }
                            >
                                Remove hypothesis
                            </LemonButton>
                        )}
                    </div>
                </LemonCard>
            ))}
        </div>
    )
}
import { useId } from 'react'
