import { Card, CardContent, Heading, Progress, ProgressLabel, Text } from '@posthog/quill'

import { ReleaseLifecycle } from './ReleaseLifecycle'
import { ReleaseNextSteps } from './ReleaseNextSteps'
import { REVIEW_AFTER_DAYS, ReleaseRow, STAGE_COLOR } from './releaseUtils'

export function ReleaseStatusCard({ row }: { row: ReleaseRow }): JSX.Element {
    return (
        <Card data-attr="release-status">
            <CardContent className="flex flex-col gap-5">
                <ReleaseLifecycle steps={row.lifecycle} color={STAGE_COLOR[row.stage]} />
                <div className="flex flex-col gap-1">
                    <Heading size="lg" render={<h2 className="m-0" />}>
                        {row.headline}
                    </Heading>
                    {row.detail && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {row.detail}
                        </Text>
                    )}
                </div>
                {row.runningDays > 0 && row.runningDays < REVIEW_AFTER_DAYS && (
                    <Progress value={(row.runningDays / REVIEW_AFTER_DAYS) * 100} className="max-w-md">
                        <ProgressLabel>Toward two weeks of data</ProgressLabel>
                        <Text size="xs" variant="muted" className="ms-auto">
                            {`${row.runningDays} of ${REVIEW_AFTER_DAYS} days`}
                        </Text>
                    </Progress>
                )}
                <ReleaseNextSteps row={row} />
            </CardContent>
        </Card>
    )
}
