import { BindLogic, useActions, useValues } from 'kea'

import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@posthog/quill'

import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import FeatureFlagSchedule from 'scenes/feature-flags/FeatureFlagSchedule'

import { releaseLogic } from './releaseLogic'

export function ReleaseScheduleDialog(): JSX.Element {
    const { scheduleFlagId, flags } = useValues(releaseLogic)
    const { closeSchedule } = useActions(releaseLogic)
    const flag = flags.find((item) => item.id === scheduleFlagId)

    return (
        <Dialog open={scheduleFlagId !== null} onOpenChange={(open: boolean) => !open && closeSchedule()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>{flag ? `Schedule a change for ${flag.key}` : 'Schedule a change'}</DialogTitle>
                    <DialogDescription>
                        PostHog changes the flag at the time you set. The change shows on the release timeline.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {scheduleFlagId !== null && (
                        <div data-not-quill>
                            <BindLogic logic={featureFlagLogic} props={{ id: scheduleFlagId }}>
                                <FeatureFlagSchedule />
                            </BindLogic>
                        </div>
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
