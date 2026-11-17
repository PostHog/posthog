import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { InvestigationDocument } from './investigationDocument'
import { InvestigationResults } from './InvestigationResults'

export function InvestigationHistory({
    document,
    onChange,
    editable,
}: {
    document: InvestigationDocument
    onChange: (document: InvestigationDocument) => void
    editable: boolean
}): JSX.Element {
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const run = document.runs.find((item) => item.id === selectedId) ?? document.runs.at(-1)
    const baseline = document.runs.find((item) => item.id === document.baselineId)
    if (!run) {
        return (
            <LemonBanner type="info">
                Run your evidence queries to capture the first snapshot. Then choose a baseline to compare future runs.
            </LemonBanner>
        )
    }
    const changedDefinitions = run.results.some(
        (result) => document.evidence.find((item) => item.id === result.evidenceId)?.sql !== result.sql
    )
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSelect
                        value={run.id}
                        onChange={setSelectedId}
                        options={document.runs
                            .map((item, index) => ({
                                value: item.id,
                                label: `Run ${index + 1}${item.id === document.baselineId ? ' (baseline)' : ''}${index === document.runs.length - 1 ? ' (latest)' : ''}`,
                            }))
                            .reverse()}
                    />
                    <TZLabel time={run.at} />
                    {run.id === baseline?.id && <LemonTag type="primary">Baseline</LemonTag>}
                </div>
                {editable && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={
                            run.id === baseline?.id
                                ? 'This run is already the baseline.'
                                : run.results.some((result) => result.error || result.truncated)
                                  ? 'Choose a run with complete, successful results.'
                                  : undefined
                        }
                        onClick={() => onChange({ ...document, baselineId: run.id })}
                        data-attr="investigation-set-baseline"
                    >
                        Use as baseline
                    </LemonButton>
                )}
            </div>
            {changedDefinitions && (
                <LemonBanner type="warning">
                    Evidence definitions have changed since this run. Rerun to capture results for the current
                    definitions.
                </LemonBanner>
            )}
            {baseline && baseline.id !== run.id && (
                <p className="text-secondary mb-0">
                    Compared with the baseline saved <TZLabel time={baseline.at} />. Differences describe results, not
                    causes.
                </p>
            )}
            <div className="grid grid-cols-1 gap-3">
                {run.results.map((result) => (
                    <InvestigationResults
                        key={result.evidenceId}
                        result={result}
                        baseline={baseline?.results.find((item) => item.evidenceId === result.evidenceId)}
                    />
                ))}
            </div>
            {run.conclusion && (
                <div className="border-t pt-4">
                    <h4>Conclusion at the time of this run</h4>
                    <p className="whitespace-pre-wrap break-words">{run.conclusion}</p>
                </div>
            )}
            <p className="text-xs text-secondary mb-0">
                The last 10 runs are retained, including your pinned baseline. Runs happen when you choose Run evidence;
                this investigation does not run in the background.
            </p>
        </div>
    )
}
