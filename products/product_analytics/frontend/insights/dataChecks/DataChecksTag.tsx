import { IconCheck, IconCircleDashed, IconWarning } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { Badge, Spinner as QuillSpinner } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'

import type { InsightDataChecksStatus } from './insightDataChecksLogic'

const TYPES: Partial<Record<InsightDataChecksStatus, LemonTagType>> = {
    passed: 'success',
    warning: 'warning',
    problem: 'danger',
}

const BADGE_VARIANTS: Partial<Record<InsightDataChecksStatus, 'success' | 'warning' | 'destructive'>> = {
    passed: 'success',
    warning: 'warning',
    problem: 'destructive',
}

export function DataChecksTag({
    status,
    label,
    labelOpen,
}: {
    status: InsightDataChecksStatus
    label: string
    labelOpen: boolean
}): JSX.Element {
    const quillSurface = useQuillSurface()

    const spinner = quillSurface ? <QuillSpinner key={status} /> : <Spinner key={status} textColored />
    const content = (
        <>
            {status === 'passed' ? (
                <IconCheck key={status} />
            ) : status === 'checking' ? (
                spinner
            ) : status === 'no_events' ||
              status === 'inconclusive' ||
              status === 'on_request' ||
              status === 'partial' ? (
                <IconCircleDashed key={status} />
            ) : (
                <IconWarning key={status} />
            )}
            <span
                className={cn(
                    'overflow-hidden whitespace-nowrap',
                    'transition-[max-width,opacity] duration-700 ease-out motion-reduce:duration-0',
                    labelOpen ? 'max-w-40 opacity-100' : 'max-w-0 opacity-0',
                    'group-hover/checks:max-w-40 group-hover/checks:opacity-100',
                    'group-focus-visible/checks:max-w-40 group-focus-visible/checks:opacity-100',
                    'group-data-popup-open/checks:max-w-40 group-data-popup-open/checks:opacity-100'
                )}
            >
                <span key={status} className="ps-1 transition-opacity duration-500 starting:opacity-0">
                    {label}
                </span>
            </span>
        </>
    )

    return quillSurface ? (
        <Badge variant={BADGE_VARIANTS[status] ?? 'default'} className="gap-0">
            {content}
        </Badge>
    ) : (
        <LemonTag type={TYPES[status] ?? 'muted'} className="gap-0">
            {content}
        </LemonTag>
    )
}
