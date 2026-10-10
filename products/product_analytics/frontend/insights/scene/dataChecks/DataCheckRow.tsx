import { Button, Dot, Text } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { DataCheck, DataCheckLevel } from './dataChecks'

const DOT_VARIANTS: Record<DataCheckLevel, 'default' | 'success' | 'warning' | 'destructive'> = {
    passed: 'success',
    warning: 'warning',
    problem: 'destructive',
    pending: 'default',
    skipped: 'default',
}

const LEVEL_LABELS: Record<DataCheckLevel, string> = {
    passed: 'Passed',
    warning: 'Warning',
    problem: 'Problem',
    pending: 'Checking',
    skipped: 'Not checked',
}

export interface DataCheckRowProps {
    check: DataCheck
    onFilterInternalUsers: () => void
}

export function DataCheckRow({ check, onFilterInternalUsers }: DataCheckRowProps): JSX.Element {
    const isFinding = check.level === 'warning' || check.level === 'problem'

    return (
        <li
            className="flex items-start gap-2"
            data-attr="quill-insight-data-check"
            data-check={check.key}
            data-level={check.level}
        >
            <span className="flex h-5 shrink-0 items-center">
                <Dot variant={DOT_VARIANTS[check.level]} pulse={check.level === 'pending'} />
            </span>
            <div className="flex min-w-0 flex-col items-start gap-0.5">
                <Text size="sm" weight="medium">
                    {check.name}
                    <span className="sr-only">{`: ${LEVEL_LABELS[check.level]}`}</span>
                </Text>
                <Text size="sm" variant={isFinding ? 'default' : 'muted'}>
                    {check.result}
                </Text>
                {check.fix && (
                    <Text size="xs" variant="muted">
                        {check.fix}
                    </Text>
                )}
                {check.action === 'filter_internal_users' && (
                    <Button
                        variant="outline"
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
        </li>
    )
}
