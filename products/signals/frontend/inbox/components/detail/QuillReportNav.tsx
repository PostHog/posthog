import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconArrowLeft, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { type HotkeyInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { inboxReportQueue } from '../../utils/reportQueue'

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
    )
}

function overlayOpen(): boolean {
    return !!document.querySelector('[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]')
}

export function QuillReportNav({
    reportId,
    backUrl,
    backLabel,
}: {
    reportId: string
    backUrl: string
    backLabel: string
}): JSX.Element {
    // Read once per report: the list keeps polling under the page, and a position that moves while a person
    // reads would make Previous and Next open a different report than the one they expect.
    const queue = useMemo(() => inboxReportQueue(reportId), [reportId])
    const open = (id: string | null): void => {
        if (id) {
            router.actions.push(urls.inboxReport('reports', id))
        }
    }
    const shortcut = (id: string | null): HotkeyInterface => ({
        action: (event: KeyboardEvent) => {
            if (!isTyping(event.target) && !overlayOpen()) {
                open(id)
            }
        },
    })

    useKeyboardHotkeys({ j: shortcut(queue?.nextId ?? null), k: shortcut(queue?.previousId ?? null) }, [queue])

    return (
        <nav className="TodayReportNav" aria-label="Reports">
            <LinkPrimitive to={backUrl} className="TodayReportNav__back" data-attr="inbox-report-back">
                <IconArrowLeft className="size-3.5" />
                <span>{backLabel}</span>
            </LinkPrimitive>
            {queue && (
                <span className="TodayReportNav__steps">
                    <span className="TodayReportNav__count" translate="no">
                        {`${queue.position} of ${queue.total}`}
                    </span>
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="Previous report"
                        tooltip="Previous report (K)"
                        disabled={!queue.previousId}
                        onClick={() => open(queue.previousId)}
                        data-attr="inbox-report-previous"
                    >
                        <IconChevronLeft />
                    </Button>
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="Next report"
                        tooltip="Next report (J)"
                        disabled={!queue.nextId}
                        onClick={() => open(queue.nextId)}
                        data-attr="inbox-report-next"
                    >
                        <IconChevronRight />
                    </Button>
                </span>
            )}
        </nav>
    )
}
