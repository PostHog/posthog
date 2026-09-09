import clsx from 'clsx'
import { useState } from 'react'

import { IconCheckCircle, IconHide, IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { InboxReportSectionKey, SignalReport } from '../../types'
import { DISMISSAL_REASON_OPTIONS, RESOLVE_REASON_OPTIONS } from '../../utils/dismissalReasons'
import { canResolveReport } from '../../utils/reportActions'
import { useReportVerdict } from './useReportVerdict'

/**
 * A reason menu for one verdict: every reason applies on click, with "Something else…" split off
 * below the canned ones. Its trailing pencil opens the dialog with that reason preselected, which is
 * the only way left to write a note, so it is a button of its own rather than the row's action.
 */
function reasonMenuItems<T extends string>({
    options,
    noteTooltip,
    dataAttrPrefix,
    onPick,
    onPickWithNote,
}: {
    options: readonly { readonly value: T; readonly label: string }[]
    noteTooltip: string
    dataAttrPrefix: string
    onPick: (reason: T) => void
    onPickWithNote: (reason: T) => void
}): LemonMenuItems {
    const other = options.find((option) => option.value === 'other')
    return [
        {
            items: options
                .filter((option) => option.value !== 'other')
                .map((option) => ({
                    label: option.label,
                    onClick: () => onPick(option.value),
                    'data-attr': `${dataAttrPrefix}-reason`,
                })),
        },
        other
            ? {
                  items: [
                      {
                          label: other.label,
                          onClick: () => onPick(other.value),
                          'data-attr': `${dataAttrPrefix}-reason`,
                          sideAction: {
                              icon: <IconPencil />,
                              tooltip: noteTooltip,
                              onClick: () => onPickWithNote(other.value),
                              'data-attr': `${dataAttrPrefix}-note`,
                          },
                      },
                  ],
              }
            : null,
    ]
}

/**
 * Resolve and Dismiss on a report row, each opening its reasons so one more click finishes the
 * verdict. Hidden until the row is hovered or focused (and while a menu is open), so a row at rest
 * still reads as the redesign's single link into the report.
 *
 * The row's own container has to be a Tailwind `group` for the hover reveal to work.
 */
export function ReportVerdictButtons({
    report,
    sectionKey,
}: {
    report: SignalReport
    /** The list state that owns the row; its keyed logic applies the optimistic update. */
    sectionKey: InboxReportSectionKey
}): JSX.Element {
    const { pickDismissReason, pickResolveReason, openDismissDialog, openResolveDialog } = useReportVerdict({
        report,
        sectionKey,
        surface: 'list_row',
    })
    // The menus render in a portal, so neither hover nor focus keeps the trigger visible while one
    // is open. Without this the buttons fade out from under the menu they opened.
    const [openMenus, setOpenMenus] = useState(0)

    return (
        <div
            data-attr="inbox-report-row-verdicts"
            className={clsx(
                'flex items-center gap-2.5 transition-opacity',
                openMenus > 0 ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100'
            )}
            onClick={(event) => {
                // The whole row is a link to the report; a verdict must not follow it.
                event.preventDefault()
                event.stopPropagation()
            }}
        >
            {canResolveReport(report) && (
                <LemonMenu
                    placement="bottom-end"
                    onVisibilityChange={(visible) => setOpenMenus((count) => count + (visible ? 1 : -1))}
                    items={reasonMenuItems({
                        options: RESOLVE_REASON_OPTIONS,
                        noteTooltip: 'Resolve and write a note',
                        dataAttrPrefix: 'inbox-report-row-resolve',
                        onPick: pickResolveReason,
                        onPickWithNote: openResolveDialog,
                    })}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCheckCircle />}
                        tooltip="Mark this report done"
                        data-attr="inbox-report-row-resolve"
                    >
                        Resolve
                    </LemonButton>
                </LemonMenu>
            )}
            <LemonMenu
                placement="bottom-end"
                onVisibilityChange={(visible) => setOpenMenus((count) => count + (visible ? 1 : -1))}
                items={reasonMenuItems({
                    options: DISMISSAL_REASON_OPTIONS,
                    noteTooltip: 'Dismiss and write a note',
                    dataAttrPrefix: 'inbox-report-row-dismiss',
                    onPick: pickDismissReason,
                    onPickWithNote: openDismissDialog,
                })}
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconHide />}
                    tooltip="Dismiss this report"
                    data-attr="inbox-report-row-dismiss"
                >
                    Dismiss
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
