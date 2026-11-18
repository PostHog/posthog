import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { ReportDecisionAttribution } from '../../utils/reportDecisions'

function DecisionAttribution({ attribution }: { attribution: ReportDecisionAttribution }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap items-center gap-1 font-semibold">
                <span>{attribution.person ? `Set by ${fullNameOrEmail(attribution.person)},` : 'Set by agent,'}</span>
                <TZLabel time={attribution.setAt} showPopover={false} />
            </div>
            {attribution.reason && <p className="m-0 whitespace-pre-wrap">{attribution.reason}</p>}
            {attribution.previousValue && <span>{`Changed from ${attribution.previousValue}`}</span>}
        </div>
    )
}

/**
 * A decision about the report, such as its repository or priority, in the Status section. Hovering or
 * focusing the value shows who set it and why. With `options` and `onChange`, picking a value saves it,
 * and the menu repeats who set it, so a tap reaches the reason too.
 */
export function ReportDecisionRow<T extends string>({
    label,
    value,
    attribution,
    options,
    onChange,
    saving = false,
    'data-attr': dataAttr,
}: {
    label: string
    value: T
    attribution: ReportDecisionAttribution | null
    options?: LemonSelectOptionLeaf<T>[]
    onChange?: (value: T) => void
    saving?: boolean
    'data-attr'?: string
}): JSX.Element {
    const details = attribution ? <DecisionAttribution attribution={attribution} /> : null

    return (
        <div className="flex min-h-6 items-center justify-between gap-3">
            <dt className="shrink-0 text-xs text-secondary">{label}</dt>
            <dd className="m-0 flex min-w-0 items-center justify-end text-right text-xs">
                {options && onChange ? (
                    <LemonSelect<T>
                        aria-label={`Change report ${label.toLowerCase()}`}
                        data-attr={dataAttr}
                        value={value}
                        onChange={onChange}
                        loading={saving}
                        disabledReason={saving ? 'Saving…' : undefined}
                        tooltip={details}
                        size="xsmall"
                        type="tertiary"
                        dropdownPlacement="bottom-end"
                        dropdownMatchSelectWidth={false}
                        menu={{ className: 'w-64' }}
                        options={
                            details
                                ? [
                                      {
                                          options,
                                          footer: (
                                              <div className="mt-1 border-t border-primary px-2 pt-2 pb-1">
                                                  {details}
                                              </div>
                                          ),
                                      },
                                  ]
                                : options
                        }
                        renderButtonContent={() => (
                            <span className="truncate text-xs font-normal text-default">{value}</span>
                        )}
                    />
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
