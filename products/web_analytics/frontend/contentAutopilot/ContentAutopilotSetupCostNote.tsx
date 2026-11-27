import { pluralize } from 'lib/utils/strings'

/** How many paid checks one run makes, in counts only. */
export const ContentAutopilotSetupCostNote = ({
    prompts,
    engines,
}: {
    prompts: number
    /** Engines that can run today. */
    engines: number
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
            Each check asks an AI engine with web search on, so you see the same answer your buyers see. Engines check
            the prompts that are on, daily or weekly. Turn off engines or prompts to spend less.
        </span>
    </div>
)
