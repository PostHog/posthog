import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'

import type { InsightLogicProps } from '~/types'

import { insightFollowUpsLogic } from './insightFollowUpsLogic'
import type { FollowUpSlot } from './insightFollowUpsLogic'

function AddFollowUp({
    insightProps,
    slot,
    label,
}: {
    insightProps: InsightLogicProps
    slot: FollowUpSlot
    label: string
}): JSX.Element {
    const { isSaved } = useValues(insightFollowUpsLogic(insightProps))
    const { startFollowUp } = useActions(insightFollowUpsLogic(insightProps))
    const { insightSaving } = useValues(insightLogic(insightProps))
    const { saveInsight } = useActions(insightLogic(insightProps))

    if (isSaved) {
        return (
            <Button
                variant="outline"
                size="sm"
                onClick={() => startFollowUp(slot)}
                data-attr={`quill-insight-add-${slot}`}
            >
                <IconPlus />
                {label}
            </Button>
        )
    }

    return (
        <Popover>
            <PopoverTrigger render={<Button variant="outline" size="sm" data-attr={`quill-insight-add-${slot}`} />}>
                <IconPlus />
                {label}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72 gap-2">
                <Text size={null}>Save this insight first. PostHog can only send or watch a saved insight.</Text>
                <Button
                    variant="primary"
                    size="sm"
                    className="self-start"
                    loading={insightSaving}
                    onClick={() => saveInsight(true)}
                    data-attr={`quill-insight-add-${slot}-save`}
                >
                    Save insight
                </Button>
            </PopoverContent>
        </Popover>
    )
}

export function FollowUpAdditions({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { alertsSupported, followUps } = useValues(insightFollowUpsLogic(insightProps))
    const has = (slot: FollowUpSlot): boolean => followUps.some((followUp) => followUp.slot === slot)

    return (
        <>
            {!has('subscription') && (
                <AddFollowUp insightProps={insightProps} slot="subscription" label="sent to my team" />
            )}
            {alertsSupported && !has('alert') && (
                <AddFollowUp insightProps={insightProps} slot="alert" label="alerting me when it changes" />
            )}
        </>
    )
}
