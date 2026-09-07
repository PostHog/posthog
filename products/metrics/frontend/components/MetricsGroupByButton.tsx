import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInputSelect } from '@posthog/lemon-ui'

import { metricsViewerLogic } from './metricsViewerLogic'

/** Group by is a button that opens the attribute multiselect, so the filter bar stays the
 * primary control (mirrors how logs and traces keep grouping as a button, not the main bar). */
export function MetricsGroupByButton({
    groupByKeys,
    onChange,
    disabledReason,
}: {
    groupByKeys: string[]
    onChange: (groupByKeys: string[]) => void
    disabledReason: string | null
}): JSX.Element {
    const { attributeKeyOptions, attributeKeyOptionsLoading } = useValues(metricsViewerLogic)
    const { setGroupBySearch, loadAttributeKeyOptions } = useActions(metricsViewerLogic)
    const [open, setOpen] = useState<boolean>(false)

    const label =
        groupByKeys.length === 0
            ? 'Group by'
            : groupByKeys.length === 1
              ? `Group by: ${groupByKeys[0]}`
              : `Group by: ${groupByKeys.length} attributes`

    return (
        <LemonDropdown
            visible={open}
            closeOnClickInside={false}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="p-1 w-[18rem]">
                    <LemonInputSelect
                        mode="multiple"
                        size="small"
                        allowCustomValues
                        value={groupByKeys}
                        onChange={onChange}
                        options={attributeKeyOptions}
                        loading={attributeKeyOptionsLoading}
                        onInputChange={setGroupBySearch}
                        onFocus={() => loadAttributeKeyOptions({})}
                        placeholder="Group by attribute…"
                        data-attr="metrics-viewer-group-by"
                        disabledReason={disabledReason}
                        autoFocus
                    />
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                active={open || groupByKeys.length > 0}
                sideIcon={<IconChevronDown />}
                onClick={() => {
                    setOpen((wasOpen) => !wasOpen)
                    loadAttributeKeyOptions({})
                }}
                disabledReason={disabledReason ?? undefined}
                data-attr="metrics-viewer-group-by-button"
                // Attribute keys can be long, so cap the trigger rather than let it push the row wide
                truncate
                className="max-w-[16rem]"
                tooltip={groupByKeys.length > 0 ? groupByKeys.join(', ') : undefined}
            >
                {label}
            </LemonButton>
        </LemonDropdown>
    )
}
