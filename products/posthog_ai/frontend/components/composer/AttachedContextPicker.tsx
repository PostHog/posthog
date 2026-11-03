import { useActions } from 'kea'

import { IconAtSign } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { CONTEXT_PICKER_GROUP_TYPES, contextPickerLogic } from '../../logics/contextPickerLogic'

export interface AttachedContextPickerProps {
    className?: string
}

export function AttachedContextPicker({ className = 'h-6 min-h-6 shrink-0' }: AttachedContextPickerProps): JSX.Element {
    const { handleTaxonomicFilterChange } = useActions(contextPickerLogic)
    return (
        <Tooltip title="Add context to help PostHog AI answer your question">
            {/* Wrapper span prevents Base UI's Tooltip.Trigger from merging
            props into TaxonomicPopover. Without it, mergeProps treats
            onChange as a DOM event handler and wraps it in a single-arg
            callback, dropping the groupType and item arguments. */}
            <span className="inline-flex">
                <TaxonomicPopover
                    size="xsmall"
                    type="tertiary"
                    className={className}
                    groupType={TaxonomicFilterGroupType.Events}
                    groupTypes={CONTEXT_PICKER_GROUP_TYPES}
                    onChange={handleTaxonomicFilterChange}
                    icon={<IconAtSign className="text-secondary" />}
                    placeholder="Add context"
                    aria-label="Add context"
                    placeholderClass="text-secondary"
                    width={450}
                    data-attr="posthog-ai-context-picker"
                />
            </span>
        </Tooltip>
    )
}
