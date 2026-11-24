import { Badge, Button, Text } from '@posthog/quill'

import type { EventsRetentionSupportPeriodProps } from './EventsRetentionSupportPeriod'
import { EventsRetentionSupportPeriodModal } from './EventsRetentionSupportPeriodModal'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export function QuillEventsRetentionSupportPeriod({
    saving,
    restrictionReason,
    changing,
    onChangingChange,
    ...modalProps
}: EventsRetentionSupportPeriodProps & {
    changing: boolean
    onChangingChange: (changing: boolean) => void
}): JSX.Element {
    return (
        <>
            <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                {retentionPeriodLabel(modalProps.supportMonths)}
            </Text>
            <Badge>Set by PostHog support</Badge>
            <Button
                variant="outline"
                onClick={() => onChangingChange(true)}
                loading={saving}
                disabledReason={restrictionReason}
                data-attr={`${modalProps.dataAttr}-change-support-period`}
            >
                Change
            </Button>
            {changing && <EventsRetentionSupportPeriodModal {...modalProps} onClose={() => onChangingChange(false)} />}
        </>
    )
}
