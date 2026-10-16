import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSwitch } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { ExcludedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconTuning } from 'lib/lemon-ui/icons'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveyResponseColumnId, surveyResponseColumnLabel } from 'scenes/surveys/utils'

import { SurveyEventName } from '~/types'

const PROPERTY_GROUP_TYPES = [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]

export function SurveyResponseColumnsMenu(): JSX.Element {
    const { responseColumns } = useValues(surveyLogic)
    const { addResponseColumn, removeResponseColumn } = useActions(surveyLogic)
    const [picking, setPicking] = useState(false)

    const personIdShown = responseColumns.some((column) => column.type === 'person_id')
    const addedPropertyKeys: ExcludedProperties = Object.fromEntries(
        PROPERTY_GROUP_TYPES.map((groupType) => [
            groupType,
            responseColumns.flatMap((column) => (column.type === groupType ? [column.key] : [])),
        ])
    )

    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-end"
            onVisibilityChange={(visible) => !visible && setPicking(false)}
            overlay={
                picking ? (
                    <TaxonomicFilter
                        taxonomicGroupTypes={PROPERTY_GROUP_TYPES}
                        eventNames={[SurveyEventName.SENT]}
                        excludedProperties={addedPropertyKeys}
                        onClose={() => setPicking(false)}
                        onChange={(group, value) => {
                            if (
                                group.type === TaxonomicFilterGroupType.EventProperties ||
                                group.type === TaxonomicFilterGroupType.PersonProperties
                            ) {
                                addResponseColumn({ type: group.type, key: String(value) })
                            }
                            setPicking(false)
                        }}
                    />
                ) : (
                    <div className="flex flex-col gap-1 py-1 px-2 min-w-64">
                        <LemonSwitch
                            checked={personIdShown}
                            onChange={(show) =>
                                show
                                    ? addResponseColumn({ type: 'person_id' })
                                    : removeResponseColumn({ type: 'person_id' })
                            }
                            label="Person ID"
                            fullWidth
                            data-attr="survey-response-column-person_id"
                        />
                        {responseColumns.map((column) =>
                            column.type === 'person_id' ? null : (
                                <div key={surveyResponseColumnId(column)} className="flex items-center gap-2">
                                    <span className="flex-1 min-w-0 truncate">{surveyResponseColumnLabel(column)}</span>
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconX />}
                                        tooltip="Remove column"
                                        onClick={() => removeResponseColumn(column)}
                                        data-attr="survey-response-column-remove"
                                    />
                                </div>
                            )
                        )}
                        <LemonButton
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => setPicking(true)}
                            fullWidth
                            data-attr="survey-response-column-add"
                        >
                            Add column
                        </LemonButton>
                    </div>
                )
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconTuning />}
                tooltip="Choose which columns appear in the table and in exports"
                data-attr="survey-response-columns-menu"
            >
                Columns
            </LemonButton>
        </LemonDropdown>
    )
}
