import { pluralize } from 'lib/utils/strings'

import { engineLabel } from './utils'

/** How many paid checks one run makes, in counts only. */
export const ContentAutopilotSetupCostNote = ({
    prompts,
    engines,
    pendingEngines = [],
}: {
    prompts: number
    /** Engines that can run today. */
    engines: number
    /** Chosen engines that are not available yet. */
    pendingEngines?: string[]
}): JSX.Element => (
    <div
        className="flex flex-col gap-1 text-xs text-secondary"
        data-attr="content-autopilot-setup-cost-note"
        data-checks={prompts * engines}
    >
        {prompts > 0 && engines > 0 ? (
            <span className="font-semibold text-default">
                About {pluralize(prompts * engines, 'check')} per run: {pluralize(prompts, 'prompt')} ×{' '}
                {pluralize(engines, 'engine')}
            </span>
        ) : null}
        <span>
            Each check is a paid call to an AI engine. Engines check your active prompts daily or weekly. Turn engines
            off or pause prompts in settings to spend less.
        </span>
        {pendingEngines.length > 0 ? (
            <span data-attr="content-autopilot-setup-pending-engines">
                Checks with {pendingEngines.map(engineLabel).join(', ')} start, and cost, once{' '}
                {pendingEngines.length === 1 ? "it's" : "they're"} available for your project.
            </span>
        ) : null}
    </div>
)
