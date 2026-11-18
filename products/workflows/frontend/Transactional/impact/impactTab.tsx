import { LemonTag } from '@posthog/lemon-ui'

import { LemonTab } from 'lib/lemon-ui/LemonTabs'

import { EmailImpactTab } from './EmailImpactTab'

export function impactTab(workflowId: string): LemonTab<'impact'> {
    return {
        key: 'impact',
        label: (
            <span className="flex items-center gap-1">
                Impact
                <LemonTag type="highlight" size="small">
                    New
                </LemonTag>
            </span>
        ),
        content: <EmailImpactTab workflowId={workflowId} />,
    }
}
