import { LemonCheckbox, LemonInput, LemonLabel, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { INVESTIGATION_CHECKS, InvestigationDocument } from './investigationDocument'

export function InvestigationOverview({
    document,
    onChange,
    editable,
}: {
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    editable: boolean
}): JSX.Element {
    const fieldId = useId()
    return (
        <div className="grid grid-cols-1 gap-6 @min-[48rem]/investigation:grid-cols-2">
            <div className="flex flex-col gap-4 min-w-0">
                <div>
                    <LemonLabel htmlFor={`${fieldId}-question`}>Question</LemonLabel>
                    <LemonInput
                        id={`${fieldId}-question`}
                        value={document.question}
                        maxLength={500}
                        disabled={!editable}
                        onChange={(question) => onChange({ ...document, question })}
                        placeholder="Why did trial conversion change?"
                        data-attr="investigation-question"
                    />
                </div>
                <div>
                    <LemonLabel htmlFor={`${fieldId}-context`}>Scope and assumptions</LemonLabel>
                    <LemonTextArea
                        id={`${fieldId}-context`}
                        value={document.context}
                        maxLength={10000}
                        disabled={!editable}
                        onChange={(context) => onChange({ ...document, context })}
                        placeholder="Define the metric, populations, dates, conversion window, and exclusions."
                        minRows={4}
                    />
                </div>
                <div>
                    <LemonLabel>Status</LemonLabel>
                    <LemonSelect
                        value={document.status}
                        disabled={!editable}
                        onChange={(status) => onChange({ ...document, status })}
                        options={[
                            { value: 'investigating', label: 'Investigating' },
                            { value: 'review', label: 'Ready for review' },
                            { value: 'monitoring', label: 'Following up' },
                            { value: 'closed', label: 'Closed' },
                        ]}
                    />
                </div>
            </div>
            <div className="flex flex-col gap-3 min-w-0">
                <div>
                    <h3 className="mb-1">Check the premise</h3>
                    <p className="text-secondary mb-4">Record what you have verified before explaining a change.</p>
                    <div className="flex flex-col gap-3">
                        {Object.entries(INVESTIGATION_CHECKS).map(([key, label]) => {
                            const check = key as keyof typeof INVESTIGATION_CHECKS
                            return (
                                <LemonCheckbox
                                    key={key}
                                    label={label}
                                    checked={document.checks.includes(check)}
                                    disabled={!editable}
                                    onChange={(checked) =>
                                        onChange({
                                            ...document,
                                            checks: checked
                                                ? [...document.checks, check]
                                                : document.checks.filter((item) => item !== check),
                                        })
                                    }
                                    data-attr={`investigation-check-${key}`}
                                />
                            )
                        })}
                    </div>
                </div>
                <div className="border-t pt-4 mt-2">
                    <h3 className="mb-1">Investigation workflow</h3>
                    <ol className="pl-5 text-secondary space-y-2">
                        <li>Add SQL queries and links in Evidence.</li>
                        <li>Run the queries and save a baseline.</li>
                        <li>Test competing explanations in Hypotheses.</li>
                        <li>Write your conclusion and next step in Report.</li>
                        <li>Rerun to compare new evidence with the baseline.</li>
                    </ol>
                </div>
            </div>
        </div>
    )
}
import { useId } from 'react'
