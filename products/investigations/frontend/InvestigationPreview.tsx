import { LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { investigationExample } from './investigationExample'
import { InvestigationResults } from './InvestigationResults'

export function InvestigationPreview(): JSX.Element {
    const example = investigationExample()
    return (
        <div className="flex flex-col gap-3 min-w-0">
            <LemonCard hoverEffect={false} className="p-4">
                <LemonTag>Example question</LemonTag>
                <h3 className="mt-3 mb-0">Why did trial conversion drop?</h3>
            </LemonCard>
            <InvestigationResults result={example.runs[1].results[0]} baseline={example.runs[0].results[0]} />
            <LemonCard hoverEffect={false} className="p-4">
                <h4 className="mb-2">Follow the evidence</h4>
                <p className="mb-0 text-secondary">
                    Compare acquisition channels, check cohort maturity, and record which explanations the evidence
                    supports.
                </p>
            </LemonCard>
        </div>
    )
}
