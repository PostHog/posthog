import { BindLogic, useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Spinner,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import FeatureFlagSchedule from 'scenes/feature-flags/FeatureFlagSchedule'
import { urls } from 'scenes/urls'

import { isRulesV2FeatureFlagConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'

import { releaseLogic } from './releaseLogic'

function ScheduleBody({ flagId }: { flagId: number }): JSX.Element {
    const { featureFlag, featureFlagLoading } = useValues(featureFlagLogic)
    const { loadFeatureFlag } = useActions(featureFlagLogic)

    if (featureFlag.id !== flagId) {
        return featureFlagLoading ? (
            <div className="flex justify-center py-8">
                <Spinner />
            </div>
        ) : (
            <div className="flex flex-col items-start gap-2 py-4">
                <Text size="xs">The flag could not load, so its schedule cannot change now.</Text>
                <Button variant="outline" onClick={loadFeatureFlag} data-attr="release-schedule-retry">
                    Try again
                </Button>
            </div>
        )
    }
    if (isRulesV2FeatureFlagConfig(featureFlag.filters as never)) {
        return (
            <div className="flex flex-col items-start gap-2 py-4">
                <Text size="xs">This flag uses rules. Schedule its changes on the flag page.</Text>
                <Button variant="outline" nativeButton={false} render={<LinkPrimitive to={urls.featureFlag(flagId)} />}>
                    Open the flag
                </Button>
            </div>
        )
    }
    return (
        <div data-not-quill>
            <FeatureFlagSchedule />
        </div>
    )
}

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
                        <BindLogic logic={featureFlagLogic} props={{ id: scheduleFlagId }}>
                            <ScheduleBody flagId={scheduleFlagId} />
                        </BindLogic>
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
