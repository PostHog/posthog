import { IconDocument } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
} from '@posthog/quill-primitives'

export function WizardRunsEmptyState({ onOpenLibrary }: { onOpenLibrary: () => void }): JSX.Element {
    return (
        <Empty className="min-h-[440px] justify-center py-16">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconDocument />
                </EmptyMedia>
                <EmptyTitle>No Wizard runs yet</EmptyTitle>
                <EmptyDescription>Choose a program from the Wizard Library to start a cloud run.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="primary" onClick={onOpenLibrary}>
                    Open Wizard Library
                </Button>
            </EmptyContent>
        </Empty>
    )
}
