import { pluralize } from 'lib/utils/strings'

/** How many paid checks one run makes, in counts only. */
export const ContentAutopilotSetupCostNote = ({
    prompts,
    engines,
}: {
    prompts: number
    engines: number
}): JSX.Element => (
    <div
        className="flex flex-col gap-1 text-xs text-secondary"
        data-attr="content-autopilot-setup-cost-note"
        data-checks={prompts * engines}
    >
        <span className="font-semibold text-default">
            About {pluralize(prompts * engines, 'check')} per run: {pluralize(prompts, 'prompt')} ×{' '}
            {pluralize(engines, 'engine')}
        </span>
        <span>
            Each check is a paid call to an AI engine. Once your prompts are set up, the daily schedule runs these
            checks every day. You can turn engines off or pause prompts in settings.
        </span>
    </div>
)
