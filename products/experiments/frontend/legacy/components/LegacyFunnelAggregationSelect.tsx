import { useValues } from 'kea'

import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'

import { groupsModel } from '~/models/groupsModel'

/**
 * @deprecated
 * Legacy funnel aggregation select for ExperimentView.
 * Frozen copy for legacy experiments - do not modify.
 * Forked from https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/insights/filters/AggregationSelect.tsx
 */
export function LegacyFunnelAggregationSelect({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)

    const UNIQUE_USERS = 'person_id'
    const baseValues = [UNIQUE_USERS]
    const optionSections: LemonSelectSection<string>[] = [
        {
            title: 'Event Aggregation',
            options: [
                {
                    value: UNIQUE_USERS,
                    label: 'Unique users',
                },
            ],
        },
    ]
    if (needsUpgradeForGroups || canStartUsingGroups) {
        // if (false) {
        optionSections[0].footer = <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} />
    } else {
        Array.from(groupTypes.values()).forEach((groupType) => {
            baseValues.push(`$group_${groupType.group_type_index}`)
            optionSections[0].options.push({
                value: `$group_${groupType.group_type_index}`,
                label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
            })
        })
    }

    baseValues.push(`properties.$session_id`)
    optionSections[0].options.push({
        value: 'properties.$session_id',
        label: `Unique sessions`,
    })
    optionSections[0].options.push({
        label: 'Custom SQL expression',
        options: [
            {
                // This is a bit of a hack so that the HogQL option is only highlighted as active when the user has
                // set a custom value (because actually _all_ the options are HogQL)
                value: !value || baseValues.includes(value) ? '' : value,
                label: <span className="font-mono">{value}</span>,
                labelInMenu: function CustomHogQLOptionWrapped({ onSelect }) {
                    return (
                        // eslint-disable-next-line react/forbid-dom-props
                        <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                            <HogQLEditor
                                onChange={onSelect}
                                value={value}
                                placeholder={
                                    "Enter SQL expression, such as:\n- distinct_id\n- properties.$session_id\n- concat(distinct_id, ' ', properties.$session_id)\n- if(1 < 2, 'one', 'two')"
                                }
                            />
                        </div>
                    )
                },
            },
        ],
    })

    return (
        <div className="flex items-center w-full gap-2">
            <span>Aggregating by</span>
            <LemonSelect
                className="flex-1"
                value={value}
                onChange={onChange}
                options={optionSections}
                dropdownMatchSelectWidth={false}
            />
        </div>
    )
}
