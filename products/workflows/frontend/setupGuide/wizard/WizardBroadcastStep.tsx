import { IconCalendar, IconLetter, IconPeople } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

const NEXT_STEPS = [
    { icon: <IconPeople />, title: 'Recipients', description: 'Pick a cohort, or filter people by their properties.' },
    { icon: <IconLetter />, title: 'Email', description: 'Choose the sender, write the subject and design the email.' },
    {
        icon: <IconCalendar />,
        title: 'Send',
        description: 'Send it now or schedule it. You review it before it goes out.',
    },
]

const SEND_ON_CALENDAR = {
    icon: <IconCalendar />,
    title: 'Send',
    description:
        'Send it now, or pick a day on a calendar of your other sends. It suggests a day that keeps people within your frequency cap.',
}

export function WizardBroadcastStep(): JSX.Element {
    const showSendCalendar = useFeatureFlag('WORKFLOWS_SEND_CALENDAR')
    const steps = showSendCalendar ? [...NEXT_STEPS.slice(0, -1), SEND_ON_CALENDAR] : NEXT_STEPS

    return (
        <ol className="m-0 flex list-none flex-col gap-4 p-0">
            {steps.map((step) => (
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
