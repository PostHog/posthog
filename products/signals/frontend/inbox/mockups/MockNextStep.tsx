import { IconClock, IconCode, IconPullRequest, IconSparkles } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import type { MockReport } from './mockupData'

export function MockNextStep({ report }: { report: MockReport }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1">
                {report.stage === 'watching' ? (
                    <Button variant="outline" className="me-1" disabled>
                        <IconClock />
                        {report.nextStep}
                    </Button>
                ) : (
                    <Button variant="primary" className="me-1">
                        {report.stage === 'review' ? <IconPullRequest /> : <IconCode />}
                        {report.nextStep}
                    </Button>
                )}
                <Button>
                    <IconSparkles />
                    Ask about it
                </Button>
            </div>
            {report.nextStepNote && (
                <Text size="xs" variant="muted" render={<p />}>
                    {report.nextStepNote}
                </Text>
            )}
        </div>
    )
}
