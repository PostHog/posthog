import type { WizardRunErrorDetails } from './wizardRunErrorCatalog'

export function WizardRunError({ error }: { error: WizardRunErrorDetails }): JSX.Element {
    return (
        <div className="space-y-2">
            <div>
                <div className="font-semibold">{error.title}</div>
                {error.description !== error.title && <div className="text-sm">{error.description}</div>}
            </div>
            {error.resolution && (
                <div>
                    <div className="text-sm font-semibold">What to do?</div>
                    <div className="text-sm">{error.resolution}</div>
                </div>
            )}
        </div>
    )
}
