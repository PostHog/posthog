import { IconCalendar, IconLetter, IconPeople } from '@posthog/icons'

const NEXT_STEPS = [
    { icon: <IconPeople />, title: 'Recipients', description: 'Pick a cohort, or filter people by their properties.' },
    { icon: <IconLetter />, title: 'Email', description: 'Choose the sender, write the subject and design the email.' },
    {
        icon: <IconCalendar />,
        title: 'Send',
        description: 'Send it now or schedule it. You review it before it goes out.',
    },
]

export function WizardBroadcastStep(): JSX.Element {
    return (
        <ol className="m-0 flex list-none flex-col gap-4 p-0">
            {NEXT_STEPS.map((step) => (
                <li key={step.title} className="flex items-start gap-3">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded bg-surface-secondary text-lg">
                        {step.icon}
                    </span>
                    <div className="flex flex-col">
                        <span className="font-semibold">{step.title}</span>
                        <span className="text-sm text-secondary">{step.description}</span>
                    </div>
                </li>
            ))}
        </ol>
    )
}
