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
        {prompts > 0 && engines > 0 ? (
            <span className="font-semibold text-default">
                About {pluralize(prompts * engines, 'check')} per run: {pluralize(prompts, 'prompt')} ×{' '}
                {pluralize(engines, 'engine')}
            </span>
        ) : null}
        <span>
            Each check is a paid call to an AI engine. Each engine checks your active prompts on its schedule, every day
            or once a week. You can turn engines off or pause prompts in settings.
        </span>
    </div>
)
