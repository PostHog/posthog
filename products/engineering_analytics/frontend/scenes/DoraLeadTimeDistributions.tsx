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
                <Section
                    id="merge-to-deploy"
                    title="Lead time distributions"
                    note={`Box per bucket: whisker ${excludeOutliers ? 'p5 to p95' : 'min to max'}, box p25 to p75, line at the median, dot at the mean. Buckets key on deploy time.`}
                    busy={doraLoading && !!dora}
                >
                    <DoraLeadTimeDistributionContent />
                </Section>
            </ScopePanel>
        </div>
    )
}
