import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { LemonSelectOptionLeaf, LemonSelectPropsNonClearable } from 'lib/lemon-ui/LemonSelect'
import { LemonSearchableSelect } from 'lib/lemon-ui/LemonSelect/LemonSearchableSelect'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { ReportDecisionAttribution } from '../../utils/reportDecisions'

function setByLabel({ person, agent }: ReportDecisionAttribution): string {
    if (!person) {
        return 'Set by agent,'
    }
    return agent ? `Set by ${fullNameOrEmail(person)} (via ${agent}),` : `Set by ${fullNameOrEmail(person)},`
}

function DecisionAttribution({ attribution }: { attribution: ReportDecisionAttribution }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap items-center gap-1 font-semibold">
                <span>{setByLabel(attribution)}</span>
                <TZLabel time={attribution.setAt} showPopover={false} />
            </div>
            {attribution.reason && <p className="m-0 whitespace-pre-wrap">{attribution.reason}</p>}
            {attribution.previousValue && <span>{`Changed from ${attribution.previousValue}`}</span>}
        </div>
    )
}

/** The menu repeats who set the value, so a tap on a phone reaches the reason without hover. */
export function ReportDecisionRow<T extends string>({
    label,
    value,
    attribution,
    options,
    onChange,
    saving = false,
    optionsLoading = false,
    searchPlaceholder,
    onMenuOpen,
    'data-attr': dataAttr,
}: {
    label: string
    value: T
    attribution: ReportDecisionAttribution | null
    options?: LemonSelectOptionLeaf<T>[]
    onChange?: (value: T) => void
    saving?: boolean
    /** Shows a spinner while the options load, without disabling the ones already there. */
    optionsLoading?: boolean
    /** Adds a search box to the menu, for a list too long to scan. */
    searchPlaceholder?: string
    onMenuOpen?: () => void
    'data-attr'?: string
}): JSX.Element {
    const details = attribution ? <DecisionAttribution attribution={attribution} /> : null
    const selectProps: LemonSelectPropsNonClearable<T> | null =
        options && onChange
            ? {
                  'aria-label': `Change report ${label.toLowerCase()}`,
                  'data-attr': dataAttr,
                  value,
                  onChange,
                  loading: saving || optionsLoading,
                  disabledReason: saving ? 'Saving…' : undefined,
                  tooltip: details,
                  size: 'xsmall',
                  type: 'tertiary',
                  dropdownPlacement: 'bottom-end',
                  dropdownMatchSelectWidth: false,
                  menu: {
                      className: 'w-64',
                      onVisibilityChange: (visible) => visible && onMenuOpen?.(),
                  },
                  options: details
                      ? [
                            {
                                options,
                                footer: <div className="mt-1 border-t border-primary px-2 pt-2 pb-1">{details}</div>,
                            },
                        ]
                      : options,
                  renderButtonContent: () => <span className="truncate text-xs font-normal text-default">{value}</span>,
              }
            : null

    return (
        <div className="flex min-h-6 items-center justify-between gap-3">
            <dt className="shrink-0 text-xs text-secondary">{label}</dt>
            <dd className="m-0 flex min-w-0 items-center justify-end text-right text-xs">
                {selectProps ? (
                    searchPlaceholder ? (
                        <LemonSearchableSelect<T>
                            {...selectProps}
                            searchPlaceholder={searchPlaceholder}
                            searchInputDataAttr={dataAttr ? `${dataAttr}-search` : undefined}
                        />
                    ) : (
                        <LemonSelect<T> {...selectProps} />
                    )
                ) : (
                    <Tooltip title={details} openOnClick>
                        <span className="truncate" tabIndex={details ? 0 : undefined} data-attr={dataAttr}>
                            {value}
                        </span>
                    </Tooltip>
                )}
            </dd>
        </div>
    )
}
