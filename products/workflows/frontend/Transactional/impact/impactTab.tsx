import { LemonTag } from '@posthog/lemon-ui'

import { LemonTab } from 'lib/lemon-ui/LemonTabs'

import { EmailImpactTab } from './EmailImpactTab'

// Only a template's own flag binds every send. A code email's flag is a default that each send can override.
export function impactTab(
    workflowId: string,
    { alwaysSensitive = false }: { alwaysSensitive?: boolean } = {}
): LemonTab<'impact'> {
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
        content: <EmailImpactTab workflowId={workflowId} alwaysSensitive={alwaysSensitive} />,
    }
}
