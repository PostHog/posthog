import { IconCheck, IconWarning } from '@posthog/icons'
import { Button, Dot, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { InsightLogicProps } from '~/types'

import { DataCheckFixActions } from './DataCheckFixActions'
import { CHECK_DESCRIPTIONS } from './dataChecks'
import type { DataCheck, DataCheckLevel } from './dataChecks'

const LEVEL_LABELS: Record<DataCheckLevel, string> = {
    passed: 'Passed',
    warning: 'Warning',
    problem: 'Problem',
    pending: 'Checking',
    skipped: 'Not checked',
}

function LevelIcon({ level }: { level: DataCheckLevel }): JSX.Element {
    if (level === 'passed') {
        return <IconCheck className="size-4 text-(--success-foreground)" />
    }
    if (level === 'warning' || level === 'problem') {
        return (
            <IconWarning
                className={
                    level === 'problem'
                        ? 'size-4 text-(--destructive-foreground)'
                        : 'size-4 text-(--warning-foreground)'
                }
            />
        )
    }
    return <Dot variant="default" pulse={level === 'pending'} />
}

export interface DataCheckRowProps {
    insightProps: InsightLogicProps
    check: DataCheck
    onFilterInternalUsers: () => void
}

export function DataCheckRow({ insightProps, check, onFilterInternalUsers }: DataCheckRowProps): JSX.Element {
    const isFinding = check.level === 'warning' || check.level === 'problem'
    const hasResult = check.level === 'passed' || isFinding || !!check.fix

    return (
        <li data-attr="quill-insight-data-check" data-check={check.key} data-level={check.level}>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <button
                            type="button"
                            data-quill
                            className="flex w-full cursor-default items-start gap-2 rounded-md border-0 bg-transparent px-2 py-1 text-start hover:bg-(--fill-hover) focus-visible:outline-2 focus-visible:outline-(--ring)"
                        />
                    }
                >
                    <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                        <LevelIcon level={check.level} />
                    </span>
                    {/* No size of its own, so the row takes the text size that quill gives a popover. */}
                    <Text
                        size={null}
                        weight={isFinding ? 'medium' : undefined}
                        variant={hasResult ? 'default' : 'muted'}
                        render={<span />}
                    >
                        {check.result}
                        <span className="sr-only">{`: ${LEVEL_LABELS[check.level]}`}</span>
                    </Text>
                </TooltipTrigger>
                <TooltipContent side="right">{CHECK_DESCRIPTIONS[check.key]}</TooltipContent>
            </Tooltip>
            {check.fix && (
                <div className="flex flex-col items-start gap-1.5 ps-8 pe-2 pt-0.5 pb-2">
                    <DataCheckFixActions insightProps={insightProps} check={check} />
                    <Text size="xs" variant="muted">
                        {check.fix}
                    </Text>
                    {check.action === 'filter_internal_users' && (
                        <Button
                            variant="link"
                            size="sm"
                            onClick={onFilterInternalUsers}
                            data-attr="quill-insight-data-check-filter-internal-users"
                        >
                            Filter them out
                        </Button>
                    )}
                    {check.action === 'open_filter_settings' && (
                        <Button
                            variant="link"
                            size="sm"
                            render={<Link to={urls.settings('environment-customization', 'internal-user-filtering')} />}
                            data-attr="quill-insight-data-check-filter-settings"
                        >
                            Open filter settings
                        </Button>
                    )}
                </div>
            )}
        </li>
    )
}
