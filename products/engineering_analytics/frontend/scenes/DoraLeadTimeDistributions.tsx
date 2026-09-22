import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { DoraLeadTimeDistributionContent } from './DoraLeadTimeDistributionContent'
import { doraLogic } from './doraLogic'

export function DoraLeadTimeDistributions(): JSX.Element {
    const { dora, doraLoading, excludeOutliers } = useValues(doraLogic)
    const { setExcludeOutliers } = useActions(doraLogic)

    return (
        <div data-attr="engineering-analytics-dora-grouped-charts">
            <ScopePanel
                controls={
                    <LemonSwitch
                        size="small"
                        bordered
                        label="Exclude outliers"
                        checked={excludeOutliers}
                        onChange={setExcludeOutliers}
                        data-attr="engineering-analytics-dora-exclude-outliers"
                    />
                }
            >
                <Section id="merge-to-deploy" title="Lead time distributions" busy={doraLoading && !!dora}>
                    <DoraLeadTimeDistributionContent />
                </Section>
            </ScopePanel>
        </div>
    )
}
