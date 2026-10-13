import { useActions, useValues } from 'kea'

import { IconCheck, IconMinus, IconWarning } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton/AgentPromptButton'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import type { InsightLogicProps } from '~/types'

import type {
    InsightDataCheckApi,
    InsightDataCheckKeyEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { dataCheckFixPrompt } from './dataCheckFixPrompt'
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

function LevelIcon({ level }: { level: InsightDataCheckApi['level'] }): JSX.Element {
    if (level === 'passed') {
        return <IconCheck className="text-success shrink-0 mt-0.5" />
    }
    if (level === 'skipped') {
        return <IconMinus className="text-secondary shrink-0 mt-0.5" />
    }
    return (
        <IconWarning className={level === 'problem' ? 'text-danger shrink-0 mt-0.5' : 'text-warning shrink-0 mt-0.5'} />
    )
}

export function InsightDataCheckRow({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element {
    const { promptContext } = useValues(insightDataChecksLogic(insightProps))
    const { filterOutInternalUsers, reportFixPromptSent } = useActions(insightDataChecksLogic(insightProps))

    return (
        <li
            className="flex items-start gap-2"
            data-attr="insight-data-check"
            data-check={check.key}
            data-level={check.level}
        >
            <LevelIcon level={check.level} />
            <div className="flex flex-col gap-1 min-w-0">
                <Tooltip title={CHECK_DESCRIPTIONS[check.key]} placement="left">
                    <span>{check.result}</span>
                </Tooltip>
                {check.fix && (
                    <>
                        <span className="text-xs text-secondary">{check.fix}</span>
                        <div className="flex flex-wrap items-center gap-2">
                            {check.action === 'filter_internal_users' && (
                                <LemonButton
                                    type="primary"
                                    size="xsmall"
                                    onClick={() => filterOutInternalUsers()}
                                    data-attr="insight-data-check-filter-internal-users"
                                >
                                    Filter them out
                                </LemonButton>
                            )}
                            {check.action === 'open_filter_settings' && (
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    to={urls.settings('environment-customization', 'internal-user-filtering')}
                                    targetBlank
                                    data-attr="insight-data-check-filter-settings"
                                >
                                    Open filter settings
                                </LemonButton>
                            )}
                            {promptContext && (
                                <AgentPromptButton
                                    storageKey="insight-data-check"
                                    size="xs"
                                    labelMode="destination"
                                    defaultAgentKey="posthog-ai"
                                    data-attr="insight-data-check-fix-with-ai"
                                    menuClassName={CLICK_OUTSIDE_BLOCK_CLASS}
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
                        </div>
                    </>
                )}
            </div>
        </li>
    )
}
