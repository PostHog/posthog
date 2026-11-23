import { useActions, useValues } from 'kea'

import { LemonCard, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { IMPACT_DATE_RANGES, emailImpactLogic } from './emailImpactLogic'

export function ConversionEventBar(): JSX.Element {
    const { event, days, impact } = useValues(emailImpactLogic)
    const { setEvent, setDays } = useActions(emailImpactLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-wrap items-center gap-2 p-3">
            <span className="font-semibold">Counts as converted</span>
            <TaxonomicPopover<string>
                size="small"
                type="secondary"
                groupType={TaxonomicFilterGroupType.Events}
                groupTypes={[TaxonomicFilterGroupType.CustomEvents, TaxonomicFilterGroupType.Events]}
                value={event ?? undefined}
                placeholder="Pick any event"
                allowClear
                onChange={(value) => setEvent(value ? String(value) : null)}
                data-attr="email-impact-event"
            />
            {event && (
                <span className="text-secondary text-sm">
                    within <span>{impact?.window_days ?? 7}</span> days of the click
                </span>
            )}
            <LemonSelect
                className="ml-auto"
                size="small"
                value={days}
                onChange={setDays}
                options={IMPACT_DATE_RANGES.map(({ value, label }) => ({ value, label }))}
                data-attr="email-impact-date-range"
            />
        </LemonCard>
    )
}
