import { useId } from 'react'

import { LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { InvestigationDocument } from './investigationDocument'

export function InvestigationReportConclusion({
    document,
    onChange,
    presenting,
}: {
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    presenting: boolean
}): JSX.Element {
    const fieldId = useId()
    return presenting ? (
        <>
            <div>
                <h4>Conclusion</h4>
                <p className="whitespace-pre-wrap break-words">
                    {document.conclusion || 'No conclusion recorded yet.'}
                </p>
            </div>
            <div>
                <h4>Decision and next step</h4>
                <p className="whitespace-pre-wrap break-words">{document.decision || 'No decision recorded yet.'}</p>
            </div>
            <div>
                <h4>Follow-up</h4>
                <p className="whitespace-pre-wrap break-words">{document.followUp || 'No follow-up recorded yet.'}</p>
            </div>
        </>
    ) : (
        <>
            <div>
                <LemonLabel htmlFor={`${fieldId}-conclusion`}>Conclusion</LemonLabel>
                <LemonTextArea
                    id={`${fieldId}-conclusion`}
                    value={document.conclusion}
                    maxLength={10000}
                    minRows={4}
                    onChange={(conclusion) => onChange({ ...document, conclusion })}
                    placeholder="Explain what the evidence supports, cite E1, E2, etc., and name what remains uncertain."
                    data-attr="investigation-conclusion"
                />
            </div>
            <div>
                <LemonLabel htmlFor={`${fieldId}-decision`}>Decision and next step</LemonLabel>
                <LemonTextArea
                    id={`${fieldId}-decision`}
                    value={document.decision}
                    maxLength={10000}
                    minRows={3}
                    onChange={(decision) => onChange({ ...document, decision })}
                    placeholder="What will you do, who owns it, and what outcome do you expect?"
                />
            </div>
            <div>
                <LemonLabel htmlFor={`${fieldId}-follow-up`}>Follow-up</LemonLabel>
                <LemonTextArea
                    id={`${fieldId}-follow-up`}
                    value={document.followUp}
                    maxLength={2000}
                    minRows={2}
                    onChange={(followUp) => onChange({ ...document, followUp })}
                    placeholder="When will you review this? Which result would change your conclusion?"
                />
            </div>
        </>
    )
}
