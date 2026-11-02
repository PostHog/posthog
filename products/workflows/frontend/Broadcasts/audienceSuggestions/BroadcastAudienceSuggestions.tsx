import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { getFilterLabel } from '~/taxonomy/helpers'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { AudienceSuggestionApi } from '../../generated/api.schemas'
import { broadcastAudienceSuggestionsLogic } from './broadcastAudienceSuggestionsLogic'

const LOADING_CARD_COUNT = 3

function audienceRule(suggestion: AudienceSuggestionApi): JSX.Element {
    // PostHog's own events show their label, like "Pageview", rather than "$pageview".
    const label = (name: string): string => getFilterLabel(name, TaxonomicFilterGroupType.Events)
    const event = <code className="text-primary">{label(suggestion.event)}</code>
    const days = `${suggestion.window_days} days`
    switch (suggestion.kind) {
        case 'not_yet':
            return (
                <>
                    Did {event} in the last {days}, but not{' '}
                    <code className="text-primary">{label(suggestion.missing_event ?? '')}</code>
                </>
            )
        case 'regulars':
            return (
                <>
                    Did {event} {suggestion.min_count}+ times in the last {days}
                </>
            )
        case 'lapsed':
            return (
                <>
                    Did {event} in the last 90 days, but not in the last {days}
                </>
            )
    }
}

export function BroadcastAudienceSuggestions(): JSX.Element | null {
    const { suggestions, generating, creatingId } = useValues(broadcastAudienceSuggestionsLogic)
    const { pickSuggestion } = useActions(broadcastAudienceSuggestionsLogic)
    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor
    )

    // Suggestions are optional: a failed or empty run shows nothing.
    if (!generating && suggestions.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 mb-4" data-attr="broadcast-audience-suggestions">
            <div className="flex items-center gap-2">
                {generating ? <Spinner className="size-4" /> : <IconSparkles className="size-4" />}
                <h3 className="mb-0 text-sm font-semibold">Audiences you could send to</h3>
                <Tooltip title="AI suggests these from your project's events. Check the audience and the email before you send.">
                    <LemonTag type="completion" size="small">
                        Beta
                    </LemonTag>
                </Tooltip>
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-2">
                {generating
                    ? Array.from({ length: LOADING_CARD_COUNT }, (_, index) => (
                          <LemonSkeleton key={index} className="h-44 rounded" />
                      ))
                    : suggestions.map((suggestion) => (
                          <LemonCard key={suggestion.id} hoverEffect={false} className="flex flex-col gap-2 p-4">
                              <div className="flex flex-col gap-1">
                                  <h4 className="mb-0 text-base font-semibold">{suggestion.name}</h4>
                                  <span className="text-xs text-secondary">
                                      <span translate="no">{humanFriendlyNumber(suggestion.reachable_count)}</span>{' '}
                                      {suggestion.reachable_count === 1 ? 'person' : 'people'} with an email
                                  </span>
                              </div>
                              <p className="mb-0 text-sm text-secondary">{suggestion.reason}</p>
                              <p className="mb-0 text-xs text-tertiary">{audienceRule(suggestion)}</p>
                              <div className="mt-auto flex pt-1">
                                  <LemonButton
                                      type="secondary"
                                      size="small"
                                      loading={creatingId === suggestion.id}
                                      disabledReason={
                                          editorDisabledReason ??
                                          (creatingId && creatingId !== suggestion.id
                                              ? 'Another audience is being created'
                                              : undefined)
                                      }
                                      onClick={() => pickSuggestion(suggestion)}
                                      data-attr="broadcast-audience-suggestion-use"
                                  >
                                      Write a broadcast
                                  </LemonButton>
                              </div>
                          </LemonCard>
                      ))}
            </div>
        </div>
    )
}
