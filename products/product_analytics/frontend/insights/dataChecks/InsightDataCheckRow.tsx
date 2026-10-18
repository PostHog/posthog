import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { Button, Dot, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { AgentPromptButton } from 'lib/components/AgentPromptButton/AgentPromptButton'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { InsightLogicProps } from '~/types'

import type {
    InsightDataCheckApi,
    InsightDataCheckKeyEnumApi,
    InsightDataCheckLevelEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { dataCheckFixPrompt } from './dataCheckFixPrompt'
import { dataCheckText } from './dataCheckText'
import { insightDataChecksLogic } from './insightDataChecksLogic'

const CHECK_DESCRIPTIONS: Record<InsightDataCheckKeyEnumApi, string> = {
    internal_users:
        "We count the events that your project's internal and test users filter would remove. Activity from your own team makes the numbers look higher than real usage.",
    local_development:
        'We look for events sent from localhost. They come from people building and testing the app, not from real users.',
    bot_traffic:
        'We read the browser details on each event and count the events from known bots, crawlers and AI agents.',
    duplicate_events:
        'We count the events where one person sent the same event from the same page twice in one second. That usually points to a tracking bug.',
}

const LEVEL_LABELS: Record<InsightDataCheckLevelEnumApi, string> = {
    passed: 'Passed',
    warning: 'Warning',
    problem: 'Problem',
    skipped: 'Not checked',
}

function LevelIcon({ level }: { level: InsightDataCheckApi['level'] }): JSX.Element {
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
    return <Dot variant="default" />
}

export function InsightDataCheckRow({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const { promptContext, filtersTestAccounts } = useValues(insightDataChecksLogic(insightProps))
    const { filterOutInternalUsers, reportFixPromptSent } = useActions(insightDataChecksLogic(insightProps))
    const text = dataCheckText(check, filtersTestAccounts)
    const isFinding = check.level === 'warning' || check.level === 'problem'

    return (
        <li data-attr="insight-data-check" data-check={check.key} data-level={check.level}>
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
                        variant={check.level === 'skipped' ? 'muted' : 'default'}
                        render={<span />}
                    >
                        {text.result}
                        <span className="sr-only">{`: ${LEVEL_LABELS[check.level]}`}</span>
                    </Text>
                </TooltipTrigger>
                <TooltipContent side="right">{CHECK_DESCRIPTIONS[check.key]}</TooltipContent>
            </Tooltip>
            {text.fix && (
                <div className="flex flex-col items-start gap-1.5 ps-8 pe-2 pt-0.5 pb-2">
                    {promptContext && (
                        <AgentPromptButton
                            size="sm"
                            variant="outline"
                            labelMode="destination"
                            data-attr="insight-data-check-fix-with-ai"
                            onRun={({ agentKey }) => reportFixPromptSent(check, agentKey)}
                            actions={[
                                {
                                    key: 'fix',
                                    label: 'fix prompt',
                                    buildPrompt: () => dataCheckFixPrompt(check, promptContext),
                                },
                            ]}
                        />
                    )}
                    <Text size="xs" variant="muted">
                        {text.fix}
                    </Text>
                    {check.action === 'filter_internal_users' && (
                        <Button
                            variant="link"
                            size="sm"
                            onClick={() => filterOutInternalUsers()}
                            data-attr="insight-data-check-filter-internal-users"
                        >
                            Filter them out
                        </Button>
                    )}
                    {check.action === 'open_filter_settings' && (
                        <Button
                            variant="link"
                            size="sm"
                            render={
                                <Link
                                    to={urls.settings('environment-customization', 'internal-user-filtering')}
                                    target="_blank"
                                />
                            }
                            data-attr="insight-data-check-filter-settings"
                        >
                            Open filter settings
                        </Button>
                    )}
                </div>
            )}
        </li>
    )
}
