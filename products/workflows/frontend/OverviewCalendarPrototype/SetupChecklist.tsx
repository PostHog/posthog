// PROTOTYPE (throwaway): what a new account sees in place of "Needs attention": the steps that fill the overview,
// including the ones that lead into other PostHog products.
import { IconCheckCircle } from '@posthog/icons'
import { Button, Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { prototypeToast } from './prototypeToast'

const STEPS = [
    { key: 'domain', label: 'Add a sending domain', done: false },
    { key: 'broadcast', label: 'Send your first broadcast', done: false },
    { key: 'goal', label: 'Pick a conversion goal', done: false },
    { key: 'replay', label: 'Turn on session replay for replay vision', done: true },
]

export function SetupChecklist(): JSX.Element {
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Get set up</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1.5">
                {STEPS.map((step) => (
                    <div key={step.key} className="flex items-center gap-2 text-xs">
                        <IconCheckCircle
                            className={
                                step.done
                                    ? 'size-4 shrink-0 text-success-foreground'
                                    : 'size-4 shrink-0 text-muted-foreground'
                            }
                        />
                        {step.done ? (
                            <span className="text-muted-foreground line-through">{step.label}</span>
                        ) : (
                            <Button
                                variant="link"
                                size="inline"
                                onClick={() => prototypeToast(step.label.toLowerCase())}
                            >
                                {step.label}
                            </Button>
                        )}
                    </div>
                ))}
            </CardContent>
        </Card>
    )
}
