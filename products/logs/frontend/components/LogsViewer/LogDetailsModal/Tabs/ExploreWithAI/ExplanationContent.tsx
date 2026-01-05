import { LemonCollapse } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ImmediateActionsSection } from './ImmediateActionsSection'
import { KeyFieldsSection } from './KeyFieldsSection'
import { ProbableCausesSection } from './ProbableCausesSection'
import { SeverityBanner } from './SeverityBanner'
import { SEVERITY_CONFIG } from './constants'
import { LogExplanation } from './types'

export interface ExplanationContentProps {
    explanation: LogExplanation
    onApplyFilter?: (filterKey: string, filterValue: string, attributeType: 'log' | 'resource') => void
}

export function ExplanationContent({ explanation, onApplyFilter }: ExplanationContentProps): JSX.Element {
    const {
        headline,
        impact_summary,
        technical_explanation,
        severity_assessment,
        probable_causes,
        immediate_actions,
        key_fields,
    } = explanation

    const config = SEVERITY_CONFIG[severity_assessment]
    const isCriticalOrError = severity_assessment === 'critical' || severity_assessment === 'error'

    const collapsePanels = [
        probable_causes.length > 0 && {
            key: 'causes',
            header: `AI hypotheses (${probable_causes.length})`,
            content: <ProbableCausesSection causes={probable_causes} />,
        },
        immediate_actions.length > 0 && {
            key: 'actions',
            header: `Suggested actions (${immediate_actions.filter((a) => a.priority === 'now').length} urgent)`,
            content: <ImmediateActionsSection actions={immediate_actions} />,
        },
        key_fields.length > 0 && {
            key: 'fields',
            header: `Key fields (${key_fields.length})`,
            content: <KeyFieldsSection fields={key_fields} onApplyFilter={onApplyFilter} />,
        },
    ].filter(Boolean)

    return (
        <div className="flex flex-col gap-3">
            {/* Severity Banner */}
            <SeverityBanner
                type={config.banner}
                headline={headline}
                impact={impact_summary}
                severityLabel={config.label}
            />

            {/* Technical Explanation */}
            {technical_explanation && (
                <div className="bg-bg-light rounded p-3 text-sm">
                    <LemonMarkdown>{technical_explanation}</LemonMarkdown>
                </div>
            )}

            {/* Collapsible Sections */}
            <LemonCollapse
                panels={collapsePanels}
                multiple
                defaultActiveKeys={isCriticalOrError ? ['causes', 'actions', 'fields'] : ['actions']}
                size="small"
            />

            {/* AI Disclaimer */}
            <p className="text-xs text-muted text-center mt-2 mb-0">
                This analysis is AI-generated and may be inaccurate. Always verify with your own investigation.
            </p>
        </div>
    )
}
