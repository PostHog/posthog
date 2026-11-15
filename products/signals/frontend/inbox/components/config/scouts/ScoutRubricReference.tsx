import { LemonBanner } from '@posthog/lemon-ui'

import type {
    ScoutRubricReferenceContextApi,
    ScoutRubricReferenceContextDocumentApi,
} from 'products/signals/frontend/generated/api.schemas'

export function ScoutRubricReference({
    reference,
}: {
    reference: ScoutRubricReferenceContextApi | ScoutRubricReferenceContextDocumentApi
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-3 break-words text-sm">
            <p className="m-0">{`${reference.skill_name} · version ${reference.skill_version}`}</p>
            {reference.description && <p className="m-0 text-secondary">{reference.description}</p>}
            <div>
                <h4>Scout instructions</h4>
                <pre className="m-0 max-h-80 overflow-y-auto whitespace-pre-wrap break-words text-xs">
                    {reference.instructions}
                </pre>
            </div>
            {reference.report_disposition_instructions && (
                <div>
                    <h4>Report requirements</h4>
                    <p className="m-0 whitespace-pre-wrap">{reference.report_disposition_instructions}</p>
                </div>
            )}
            {reference.reference_texts.map((file) => (
                <div key={file.path}>
                    <h4 className="break-all">{file.path}</h4>
                    <pre className="m-0 max-h-80 overflow-y-auto whitespace-pre-wrap break-words text-xs">
                        {file.content}
                    </pre>
                </div>
            ))}
            {(reference.instructions_truncated ||
                reference.reference_files_truncated ||
                reference.reference_limits.omitted_files > 0 ||
                reference.reference_limits.truncated_files.length > 0) && (
                <LemonBanner type="warning">
                    Scoring is unavailable because some instructions or reference files were shortened or omitted.
                    Generate suggestions again, review and use the new reference, then save your rubric. You can keep
                    your existing criteria.
                </LemonBanner>
            )}
        </div>
    )
}
