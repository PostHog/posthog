import { useState } from 'react'

import { LemonBanner, LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { INVESTIGATION_CHECKS, InvestigationDocument, getInvestigationLink } from './investigationDocument'
import { InvestigationReportConclusion } from './InvestigationReportConclusion'
import { InvestigationResults } from './InvestigationResults'

export function InvestigationReport({
    document,
    onChange,
    editable,
}: {
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    editable: boolean
}): JSX.Element {
    const [presenting, setPresenting] = useState(!editable)
    const latest = document.runs.at(-1)
    const baseline = document.runs.find((run) => run.id === document.baselineId)
    return (
        <div className="flex flex-col gap-4" data-attr="investigation-report">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 break-words">{document.question || 'Investigation report'}</h3>
                {editable && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setPresenting(!presenting)}
                        data-attr="investigation-present"
                    >
                        {presenting ? 'Edit report' : 'Present report'}
                    </LemonButton>
                )}
            </div>
            {document.checks.length < Object.keys(INVESTIGATION_CHECKS).length && (
                <LemonBanner type="warning">
                    Some premise checks are still unverified. Review them in Overview before relying on this conclusion.
                </LemonBanner>
            )}
            {latest && (
                <div className="text-secondary text-sm">
                    Latest evidence run: <TZLabel time={latest.at} />
                </div>
            )}
            {document.context && <p className="whitespace-pre-wrap break-words">{document.context}</p>}
            <InvestigationReportConclusion
                document={document}
                onChange={onChange}
                presenting={presenting || !editable}
            />
            {!!document.hypotheses.length && (
                <div className="border-t pt-4">
                    <h4>Explanations considered</h4>
                    <div className="flex flex-col gap-3">
                        {document.hypotheses.map((item) => (
                            <div key={item.id}>
                                <div className="flex flex-wrap items-center gap-2">
                                    <strong>{item.title || 'Untitled hypothesis'}</strong>
                                    <LemonTag type={item.status === 'supported' ? 'success' : 'default'}>
                                        {item.status === 'ruled_out'
                                            ? 'Ruled out'
                                            : item.status === 'supported'
                                              ? 'Supported'
                                              : 'Open'}
                                    </LemonTag>
                                </div>
                                <p className="whitespace-pre-wrap break-words mt-1 mb-1">
                                    {item.reasoning || 'No reasoning recorded.'}
                                </p>
                                <span className="text-xs text-secondary">
                                    {item.evidenceIds
                                        .map((id) => {
                                            const evidence = document.evidence.find((evidence) => evidence.id === id)
                                            return evidence ? `E${evidence.reference}` : 'Removed evidence'
                                        })
                                        .join(', ') || 'No evidence linked'}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {!!document.evidence.length && (
                <div className="border-t pt-4">
                    <h4>Evidence</h4>
                    <div className="flex flex-col gap-3">
                        {document.evidence.map((item) => {
                            const result = latest?.results.find((result) => result.evidenceId === item.id)
                            return (
                                <div key={item.id}>
                                    <div className="flex flex-wrap gap-2 items-center mb-2">
                                        <LemonTag>{`E${item.reference}`}</LemonTag>
                                        <strong className="break-words">{item.title}</strong>
                                        {item.kind === 'link' && getInvestigationLink(item.url) && (
                                            <Link to={getInvestigationLink(item.url)!} target="_blank">
                                                Open source
                                            </Link>
                                        )}
                                    </div>
                                    {item.note && <p className="whitespace-pre-wrap break-words">{item.note}</p>}
                                    {result ? (
                                        <>
                                            <InvestigationResults
                                                result={result}
                                                baseline={baseline?.results.find(
                                                    (previous) => previous.evidenceId === item.id
                                                )}
                                            />
                                            {result.sql !== item.sql && (
                                                <LemonBanner type="warning">
                                                    This result uses an older query definition. Rerun the investigation.
                                                </LemonBanner>
                                            )}
                                        </>
                                    ) : (
                                        item.kind === 'query' && (
                                            <LemonBanner type="info">This query has not been run.</LemonBanner>
                                        )
                                    )}
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}
            <p className="text-xs text-secondary border-t pt-3 mb-0">
                Associations and individual replays do not establish causality. Share this notebook for review, or use
                the notebook menu to print or export it.
            </p>
        </div>
    )
}
