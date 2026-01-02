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
    // Handle both new and potentially cached old schema responses
    const headline = explanation.headline ?? 'Log Analysis'
    const impactSummary = explanation.impact_summary ?? ''
    const technicalExplanation = explanation.technical_explanation ?? ''
    const severityAssessment = explanation.severity_assessment ?? 'ok'

    const config = SEVERITY_CONFIG[severityAssessment] ?? SEVERITY_CONFIG.ok
    const isCriticalOrError = severityAssessment === 'critical' || severityAssessment === 'error'

    const probableCauses = explanation.probable_causes ?? []
    const immediateActions = explanation.immediate_actions ?? []
    const keyFields = explanation.key_fields ?? []

    const collapsePanels = [
        probableCauses.length > 0 && {
            key: 'causes',
            header: `AI hypotheses (${probableCauses.length})`,
            content: <ProbableCausesSection causes={probableCauses} />,
        },
        immediateActions.length > 0 && {
            key: 'actions',
            header: `Suggested actions (${immediateActions.filter((a) => a.priority === 'now').length} urgent)`,
            content: <ImmediateActionsSection actions={immediateActions} />,
        },
        keyFields.length > 0 && {
            key: 'fields',
            header: `Key fields (${keyFields.length})`,
            content: <KeyFieldsSection fields={keyFields} onApplyFilter={onApplyFilter} />,
        },
    ].filter(Boolean)

    return (
        <div className="flex flex-col gap-3">
            {/* Severity Banner */}
            <SeverityBanner
                type={config.banner}
                headline={headline}
                impact={impactSummary}
                severityLabel={config.label}
            />

            {/* Technical Explanation */}
            {technicalExplanation && (
                <div className="bg-bg-light rounded p-3 text-sm">
                    <LemonMarkdown>{technicalExplanation}</LemonMarkdown>
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
