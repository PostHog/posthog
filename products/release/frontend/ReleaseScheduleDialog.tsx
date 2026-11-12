import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

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
import { FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'
import { urls } from 'scenes/urls'

import { isV1FeatureFlagConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'

import { releaseLogic } from './releaseLogic'

function ScheduleBody({ flagId }: { flagId: number }): JSX.Element {
    const { featureFlag, featureFlagLoading } = useValues(featureFlagLogic)
    const { loadFeatureFlag, setSelectedTab } = useActions(featureFlagLogic)

    useEffect(() => {
        setSelectedTab(FeatureFlagsTab.SCHEDULE)
    }, [setSelectedTab])

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
    if (!isV1FeatureFlagConfig(featureFlag.filters as never)) {
        return (
            <div className="flex flex-col items-start gap-2 py-4">
                <Text size="xs">This flag uses a newer configuration. Schedule its changes on the flag page.</Text>
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

function ScheduleDialog({ flagId }: { flagId: number }): JSX.Element {
    const { flags } = useValues(releaseLogic)
    const { closeSchedule } = useActions(releaseLogic)
    const { scheduledChangeLoading } = useValues(featureFlagLogic)
    const flag = flags.find((item) => item.id === flagId)

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !scheduledChangeLoading && closeSchedule()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>{flag ? `Schedule a change for ${flag.key}` : 'Schedule a change'}</DialogTitle>
                    <DialogDescription>
                        PostHog changes the flag at the time you set. The change shows on the release timeline.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <ScheduleBody flagId={flagId} />
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

export function ReleaseScheduleDialog(): JSX.Element | null {
    const { scheduleFlagId } = useValues(releaseLogic)

    if (scheduleFlagId === null) {
        return null
    }
    return (
        <BindLogic logic={featureFlagLogic} props={{ id: scheduleFlagId }}>
            <ScheduleDialog flagId={scheduleFlagId} />
        </BindLogic>
    )
}
