import { IconDocument } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export function WizardRunsEmptyState({ onOpenLibrary }: { onOpenLibrary: () => void }): JSX.Element {
    return (
        <div className="flex min-h-[440px] flex-col items-center justify-center gap-3 py-16 text-center">
            <IconDocument className="text-4xl text-muted" />
            <div className="font-semibold">No Wizard runs yet</div>
            <p className="m-0 max-w-md text-sm text-muted">
                Choose a program from the Wizard Library to start in the cloud or run it from your project folder.
            </p>
            <LemonButton type="primary" onClick={onOpenLibrary}>
                Open Wizard Library
            </LemonButton>
        </div>
    )
}
