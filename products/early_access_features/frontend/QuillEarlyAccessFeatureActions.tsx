import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType, EarlyAccessFeatureStage } from '~/types'

import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'

const RELEASE_STAGES: { label: string; tooltip: string; stage: EarlyAccessFeatureStage }[] = [
    {
        label: 'Concept',
        tooltip: 'Users can opt in to register interest, but the feature flag will not be enabled for them.',
        stage: EarlyAccessFeatureStage.Concept,
    },
    {
        label: 'Alpha',
        tooltip: 'Early testing. Opted-in users will have the feature flag enabled.',
        stage: EarlyAccessFeatureStage.Alpha,
    },
    {
        label: 'Beta (default)',
        tooltip: 'Wider testing. Opted-in users will have the feature flag enabled.',
        stage: EarlyAccessFeatureStage.Beta,
    },
    {
        label: 'General availability',
        tooltip: 'Feature becomes read-only. All opted-in users retain access.',
        stage: EarlyAccessFeatureStage.GeneralAvailability,
    },
]

export interface QuillEarlyAccessFeatureActionsProps {
    isNewEarlyAccessFeature: boolean
    canShowSaveButtons: boolean
    userAccessLevel?: AccessControlLevel
    accessControlDisabledReason: string | null
    onCancel: () => void
}

export function QuillEarlyAccessFeatureActions({
    isNewEarlyAccessFeature,
    canShowSaveButtons,
    userAccessLevel,
    accessControlDisabledReason,
    onCancel,
}: QuillEarlyAccessFeatureActionsProps): JSX.Element | null {
    const { earlyAccessFeature, earlyAccessFeatureLoading, isEarlyAccessFeatureSubmitting } =
        useValues(earlyAccessFeatureLogic)
    const { editFeature, updateStage, submitEarlyAccessFeature } = useActions(earlyAccessFeatureLogic)

    if (earlyAccessFeatureLoading) {
        return null
    }

    if (canShowSaveButtons) {
        return (
            <>
                <Button
                    variant="outline"
                    data-attr="cancel-feature"
                    onClick={onCancel}
                    disabledReason={isEarlyAccessFeatureSubmitting ? 'Saving…' : undefined}
                >
                    Cancel
                </Button>
                <AccessControlAction
                    resourceType={AccessControlResourceType.EarlyAccessFeature}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={userAccessLevel}
                >
                    <Button
                        variant="primary"
                        onClick={submitEarlyAccessFeature}
                        data-attr="save-feature"
                        loading={isEarlyAccessFeatureSubmitting}
                    >
                        {isNewEarlyAccessFeature ? 'Save as draft' : 'Save'}
                    </Button>
                </AccessControlAction>
            </>
        )
    }

    return (
        <>
            {earlyAccessFeature.stage == EarlyAccessFeatureStage.Draft && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="primary"
                                tooltip="Publish this feature to make it available"
                                disabledReason={accessControlDisabledReason}
                            />
                        }
                    >
                        Release
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-48">
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Choose stage</DropdownMenuLabel>
                            {RELEASE_STAGES.map(({ label, tooltip, stage }) => (
                                <Tooltip key={stage}>
                                    <TooltipTrigger render={<DropdownMenuItem onClick={() => updateStage(stage)} />}>
                                        {label}
                                    </TooltipTrigger>
                                    <TooltipContent side="left">{tooltip}</TooltipContent>
                                </Tooltip>
                            ))}
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            {earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.EarlyAccessFeature}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={userAccessLevel}
                >
                    <Button variant="outline" onClick={() => editFeature(true)} data-attr="edit-feature">
                        Edit
                    </Button>
                </AccessControlAction>
            )}
        </>
    )
}
