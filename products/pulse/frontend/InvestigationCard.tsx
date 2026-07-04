import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { InvestigationFinding, pulseLogic } from './pulseLogic'

/** The goal-investigation findings of the shown brief: per finding the planner's question, the
 * deterministic result summary, and the raw HogQL behind an expandable panel. The "Query <n>"
 * tags match the `query:<n>` citations rendered on sections. */
export function InvestigationCard(): JSX.Element | null {
    const { briefDetailInvestigation } = useValues(pulseLogic)

    if (briefDetailInvestigation.length === 0) {
        return null
    }

    return (
        <div className="border rounded p-4 flex flex-col gap-3">
            <h3 className="mb-0">Goal investigation</h3>
            {briefDetailInvestigation.map((finding, index) => (
                <InvestigationFindingRow key={index} finding={finding} index={index} />
            ))}
        </div>
    )
}

function InvestigationFindingRow({ finding, index }: { finding: InvestigationFinding; index: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <LemonTag>Query {index + 1}</LemonTag>
                <span className="font-medium">{finding.question}</span>
                {!finding.succeeded && <LemonTag type="danger">failed</LemonTag>}
            </div>
            {/* Result summaries are preformatted query output — keep the executor's line structure. */}
            <p className="mb-0 text-sm whitespace-pre-wrap">{finding.result_summary}</p>
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'hogql',
                        header: 'HogQL',
                        content: <CodeSnippet language={Language.SQL}>{finding.hogql}</CodeSnippet>,
                    },
                ]}
            />
        </div>
    )
}
