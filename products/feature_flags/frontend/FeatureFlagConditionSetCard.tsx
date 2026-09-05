import { IconFlag } from '@posthog/icons'
import { LemonButton, LemonSnack, LemonTag } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconOpenInNew, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { isDistinctIdFilter, withResolvedFlagLabels } from 'scenes/feature-flags/featureFlagReleaseConditionsLogic'
import { urls } from 'scenes/urls'

import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType } from '~/types'

export interface FeatureFlagConditionSetCardProps {
    group: FeatureFlagGroupType
    index: number
    aggregationTargetName: string
    getDistinctIdName: (distinctId: string) => string
    getFlagKey: (flagId: string) => string
    tag?: JSX.Element | null
    previousRolloutPercentage?: number
}

/** Extract server-provided group_key_names from a property, if present. */
function getGroupKeyNames(property: AnyPropertyFilter): Record<string, string> {
    if (property.type === PropertyFilterType.Group && 'group_key_names' in property) {
        return (property as any).group_key_names ?? {}
    }
    return {}
}

function PropertyValueDisplay({
    property,
    getDistinctIdName,
}: {
    property: AnyPropertyFilter
    getDistinctIdName: (distinctId: string) => string
}): JSX.Element {
    if (property.type === PropertyFilterType.Cohort) {
        return (
            <LemonButton type="secondary" size="xsmall" to={urls.cohort(property.value)} sideIcon={<IconOpenInNew />}>
                {property.cohort_name || `ID ${property.value}`}
            </LemonButton>
        )
    }

    const propertyValues = Array.isArray(property.value) ? property.value : [property.value]
    const groupKeyNames = property.key === '$group_key' ? getGroupKeyNames(property) : {}
    const isDistinctId = isDistinctIdFilter(property)

    return (
        <>
            {propertyValues.map((val, idx) => {
                const strVal = String(val)
                const display = isDistinctId ? getDistinctIdName(strVal) : groupKeyNames[strVal] || strVal
                return <LemonSnack key={idx}>{display}</LemonSnack>
            })}
        </>
    )
}

function PropertyFilterRow({
    property,
    isFirst,
    getDistinctIdName,
}: {
    property: AnyPropertyFilter
    isFirst: boolean
    getDistinctIdName: (distinctId: string) => string
}): JSX.Element {
    const propertyLabel =
        property.type === PropertyFilterType.Cohort || property.type === PropertyFilterType.Flag
            ? null
            : getFilterLabel(
                  property.key,
                  property.type === PropertyFilterType.Person
                      ? TaxonomicFilterGroupType.PersonProperties
                      : TaxonomicFilterGroupType.EventProperties
              )

    const operator = isPropertyFilterWithOperator(property) ? allOperatorsToHumanName(property.operator) : 'equals'

    return (
        <div className="flex items-center gap-1.5 flex-wrap text-sm">
            {isFirst ? (
                <LemonButton icon={<IconSubArrowRight className="arrow-right" />} size="small" noPadding />
            ) : (
                <LemonButton icon={<span className="text-xs font-medium">&</span>} size="small" noPadding />
            )}
            {propertyLabel && propertyLabel !== property.key && <span className="text-muted">{propertyLabel}</span>}
            {property.type === PropertyFilterType.Flag ? (
                <LemonSnack>
                    <IconFlag className="mr-1" />
                    {property.label || property.key}
                </LemonSnack>
            ) : (
                <LemonSnack>{property.type === PropertyFilterType.Cohort ? 'Cohort' : property.key}</LemonSnack>
            )}
            <span className="text-muted">{operator}</span>
            <PropertyValueDisplay property={property} getDistinctIdName={getDistinctIdName} />
        </div>
    )
}

export function FeatureFlagConditionSetCard({
    group,
    index,
    aggregationTargetName,
    getDistinctIdName,
    getFlagKey,
    tag,
    previousRolloutPercentage,
}: FeatureFlagConditionSetCardProps): JSX.Element {
    const properties = withResolvedFlagLabels(group.properties, getFlagKey)
    const rollout = group.rollout_percentage ?? 100
    const rolloutChanged = previousRolloutPercentage !== undefined && previousRolloutPercentage !== rollout

    const getSummary = (): JSX.Element => {
        if (properties.length === 0) {
            return (
                <>
                    Condition set will match <b>all {aggregationTargetName}</b>
                </>
            )
        }
        return (
            <>
                Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
            </>
        )
    }

    return (
        <div className="border rounded p-4 bg-surface-primary">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonSnack>Set {index + 1}</LemonSnack>
                <span className="text-sm">{getSummary()}</span>
                {tag}
            </div>

            {group.description && <div className="mt-2 text-sm text-muted">{group.description}</div>}

            {properties.length > 0 && (
                <div className="mt-3 flex flex-col gap-1">
                    {properties.map((property, idx) => (
                        <PropertyFilterRow
                            key={idx}
                            property={property}
                            isFirst={idx === 0}
                            getDistinctIdName={getDistinctIdName}
                        />
                    ))}
                </div>
            )}

            <div className="mt-3">
                <LemonTag type={rollout === 100 ? 'highlight' : rollout === 0 ? 'caution' : 'none'}>
                    <span className="text-sm">
                        Rolled out to <b className="tabular-nums">{rollout}%</b> of <b>{aggregationTargetName}</b> in
                        this set.
                        {rolloutChanged && (
                            <>
                                {' '}
                                Was <b className="tabular-nums">{previousRolloutPercentage}%</b>.
                            </>
                        )}
                    </span>
                </LemonTag>
            </div>

            {group.variant && (
                <div className="mt-3 text-sm">
                    All <b>{aggregationTargetName}</b> in this set will be in variant <b>{group.variant}</b>
                </div>
            )}
        </div>
    )
}
