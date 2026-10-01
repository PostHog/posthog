import { useActions, useValues } from 'kea'

import { IconAtSign } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { attachedContextLogic } from '../../logics/attachedContextLogic'
import { contextPickerLogic } from '../../logics/contextPickerLogic'

const PICKER_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.Insights,
    TaxonomicFilterGroupType.Dashboards,
    TaxonomicFilterGroupType.Notebooks,
    TaxonomicFilterGroupType.ErrorTrackingIssues,
]

export interface AttachedContextPickerProps {
    className?: string
}

export function AttachedContextPicker({ className = 'flex-shrink-0 border' }: AttachedContextPickerProps): JSX.Element {
    const { hasContext } = useValues(attachedContextLogic)
    const { handleTaxonomicFilterChange } = useActions(contextPickerLogic)
    return (
        <Tooltip title="Add context to help PostHog AI answer your question">
            {/* Wrapper span prevents Base UI's Tooltip.Trigger from merging
            props into TaxonomicPopover. Without it, mergeProps treats
            onChange as a DOM event handler and wraps it in a single-arg
            callback, dropping the groupType and item arguments. */}
            <span>
                <TaxonomicPopover
                    size="xxsmall"
                    type="tertiary"
                    className={className}
                    groupType={TaxonomicFilterGroupType.Events}
                    groupTypes={PICKER_GROUP_TYPES}
                    onChange={handleTaxonomicFilterChange}
                    icon={<IconAtSign className="text-secondary" />}
                    placeholder={hasContext ? null : 'Add context'}
                    placeholderClass="text-secondary"
                    width={450}
                    data-attr="posthog-ai-context-picker"
                />
            </span>
        </Tooltip>
    )
}
