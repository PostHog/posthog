import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'
import { urls } from 'scenes/urls'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { scoutSuggestionsLogic } from '../../logics/scoutSuggestionsLogic'
import { suggestionCadenceLabel } from '../../utils/scoutSuggestions'
import { AutonomySettingGroup } from '../config/AutonomySettingGroup'
import { useScoutCreateDisabledReason } from '../config/scouts/ScoutCreateModalHost'

export function InboxSetupScoutsStep(): JSX.Element {
    const { draft, saving, scoutChoices, scoutsLoading } = useValues(inboxSetupLogic)
    const { toggleSuggestion } = useActions(inboxSetupLogic)
    const { batchStatus } = useValues(scoutSuggestionsLogic)
    const creationDisabledReason = useScoutCreateDisabledReason()
    const selectedIds = new Set(draft.suggestions.map((item) => item.id))
    const items = scoutChoices
    return (
        <GuidedWizardSection
            title="Add scouts to look for problems"
            className="flex min-h-0 flex-col"
            headerClassName="shrink-0"
            contentClassName="flex min-h-0 flex-col"
            description={
                <>
                    Scouts are background agents that can monitor why customers drop off from a funnel or investigate
                    recurring errors. Each scout remembers what it learns across runs, shares memory with other scouts,
                    and uses{' '}
                    <Link to={urls.settings('mcp-servers')} target="_blank">
                        MCPs
                    </Link>
                    .
                </>
            }
        >
            {!items.length && scoutsLoading ? (
                <>
                    <LemonSkeleton className="h-24" />
                    <p className="text-secondary">Preparing suggestions.</p>
                </>
            ) : null}
            {!items.length && !scoutsLoading ? (
                <LemonBanner type="info">
                    {batchStatus === 'failed'
                        ? "We couldn't prepare suggestions. You can add scouts later."
                        : 'No scout suggestions yet. You can create one later.'}
                </LemonBanner>
            ) : null}
            <ul
                className="m-0 min-h-0 max-h-80 list-none overflow-y-auto overscroll-contain divide-y border-primary p-0 pr-2 [scrollbar-gutter:stable]"
                aria-label="Scout suggestions"
                tabIndex={0}
            >
                {items.map((item) => (
                    <li key={item.id} className="flex flex-wrap items-start gap-3 py-4">
                        <div className="flex-1 min-w-48">
                            <h3 className="m-0 text-sm font-semibold">{item.title}</h3>
                            <p className="mt-1 mb-1 text-xs text-secondary">{item.why_here}</p>
                            <span className="text-xs text-tertiary">
                                {`Runs ${suggestionCadenceLabel(item.proposed_config)}`}
                            </span>
                        </div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={selectedIds.has(item.id) ? <IconCheck /> : <IconPlus />}
                            disabledReason={
                                saving
                                    ? 'Saving setup'
                                    : !selectedIds.has(item.id)
                                      ? (creationDisabledReason ??
                                        (draft.suggestions.length >= 5 ? 'Select up to five scouts' : undefined))
                                      : undefined
                            }
                            onClick={() => toggleSuggestion(item)}
                            data-attr="inbox-setup-select-scout"
                        >
                            {selectedIds.has(item.id) ? 'Selected' : 'Add scout'}
                        </LemonButton>
                    </li>
                ))}
            </ul>
            <div className="shrink-0 border-t border-primary pt-4">
                <AutonomySettingGroup title="Create a scout for your product">
                    <p className="m-0 py-3 text-xs leading-snug text-secondary">
                        Describe what to watch to PostHog AI, the PostHog Slack Bot, or an agent connected through{' '}
                        <Link to="https://posthog.com/docs/model-context-protocol" target="_blank">
                            MCP
                        </Link>
                        .
                    </p>
                </AutonomySettingGroup>
            </div>
        </GuidedWizardSection>
    )
}
