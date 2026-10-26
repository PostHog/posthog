import { LemonCard } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { AEOPromptEngineStatsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { engineLabel } from './utils'

export const ContentAutopilotPromptEngineSummary = ({
    engines,
}: {
    engines: AEOPromptEngineStatsApi[]
}): JSX.Element => (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-2">
        {engines.map((engine) => (
            <LemonCard key={engine.engine} hoverEffect={false} className="p-3 flex flex-col gap-1">
                <span className="text-muted text-xs font-semibold uppercase">{engineLabel(engine.engine)}</span>
                <span className="text-2xl font-semibold">
                    {engine.citation_rate === null ? 'No answers' : `${Math.round(engine.citation_rate * 100)}%`}
                </span>
                <span className="text-muted text-xs">
                    Cited in {engine.cited} of {pluralize(engine.checks - engine.failed, 'answer')}
                </span>
                <span className="text-muted text-xs">
                    {pluralize(engine.checks, 'check')}, {engine.failed} failed
                </span>
            </LemonCard>
        ))}
    </div>
)
