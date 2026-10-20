import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DatabaseSchemaField, RetentionFilter } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

import { PROPERTY_MATH_DEFINITIONS } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

const aggregationTypeToTaxonomicType = {
    event: TaxonomicFilterGroupType.EventProperties,
    person: TaxonomicFilterGroupType.PersonProperties,
    data_warehouse: TaxonomicFilterGroupType.DataWarehouseProperties,
} satisfies Record<NonNullable<RetentionFilter['aggregationPropertyType']>, TaxonomicFilterGroupType>

const taxonomicTypeToAggregationTypeMap = Object.fromEntries(
    Object.entries(aggregationTypeToTaxonomicType).map(([aggregationType, taxonomicType]) => [
        taxonomicType,
        aggregationType,
    ])
) as Record<TaxonomicFilterGroupType, RetentionFilter['aggregationPropertyType']>

type RetentionAggregationType = 'count' | 'avg' | 'sum'

export function QuillRetentionAggregationSelector(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { allTablesMap } = useValues(databaseTableListLogic)

    const aggregationType = retentionFilter?.aggregationType || 'count'
    const aggregationProperty = retentionFilter?.aggregationProperty
    const aggregationPropertyType = retentionFilter?.aggregationPropertyType || 'event'
    const isPropertyValueAggregation = aggregationType === 'sum' || aggregationType === 'avg'

    const returningEntity = retentionFilter?.returningEntity
    const isReturningDwh = returningEntity?.type === 'data_warehouse'
    const dwhTableName = returningEntity
        ? (returningEntity.table_name ?? (returningEntity.id as string | undefined))
        : null
    const schemaColumns: DatabaseSchemaField[] = dwhTableName
        ? Object.values(allTablesMap[dwhTableName]?.fields ?? {})
        : []

    const propertyGroupType = aggregationTypeToTaxonomicType[aggregationPropertyType]
    const groupTypes = isReturningDwh
        ? [TaxonomicFilterGroupType.DataWarehouseProperties]
        : [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]
    const propertyMathName =
        PROPERTY_MATH_DEFINITIONS[
            aggregationType === 'sum' ? PropertyMathType.Sum : PropertyMathType.Average
        ].name.toLowerCase()

    return (
        <div className="flex flex-col items-start gap-2">
            <QuillSelect<RetentionAggregationType>
                value={aggregationType as RetentionAggregationType}
                onChange={(value) =>
                    updateInsightFilter(
                        value === 'count'
                            ? { aggregationType: 'count', aggregationProperty: undefined }
                            : { aggregationType: value }
                    )
                }
                options={[
                    {
                        options: [
                            {
                                value: 'count',
                                label: 'Retention rate',
                                description: 'The percentage of users who return in the specific interval',
                            },
                        ],
                    },
                    {
                        label: 'Property value',
                        options: [PropertyMathType.Average, PropertyMathType.Sum].map((mathType) => ({
                            value: mathType as RetentionAggregationType,
                            label: `Property value ${PROPERTY_MATH_DEFINITIONS[mathType].shortName}`,
                            description: PROPERTY_MATH_DEFINITIONS[mathType].description,
                        })),
                    },
                ]}
                data-attr="retention-aggregation-type-selector"
            />

            {isPropertyValueAggregation && (
                <>
                    <TaxonomicStringPopover
                        groupType={propertyGroupType}
                        groupTypes={groupTypes}
                        schemaColumns={schemaColumns}
                        showNumericalPropsOnly={true}
                        value={aggregationProperty || ''}
                        onChange={(val, groupType) => {
                            updateInsightFilter({
                                aggregationProperty: val,
                                aggregationPropertyType: taxonomicTypeToAggregationTypeMap[groupType],
                            })
                        }}
                        placeholder="Select property"
                        data-attr="retention-aggregation-property-selector"
                        selectingKeyOnly
                        renderValue={(currentValue) => (
                            <PropertyKeyInfo value={currentValue} disablePopover type={propertyGroupType} />
                        )}
                    />
                    {aggregationProperty ? (
                        <Text size="xs" variant="muted" className="m-0">
                            Calculates the {propertyMathName} from the {aggregationPropertyType.replace('_', ' ')}{' '}
                            property.
                            {aggregationPropertyType === 'event'
                                ? ' Only events where it is set to a number are counted.'
                                : null}
                        </Text>
                    ) : null}
                </>
            )}
        </div>
    )
}
