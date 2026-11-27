import { LemonButton } from '@posthog/lemon-ui'

import { AdventDoor } from './adventGraph'

export interface AdventDoorAnswerProps {
    door: AdventDoor
    onAnswer: (doorId: string, optionId: string) => void
}

export function AdventDoorAnswer({ door, onAnswer }: AdventDoorAnswerProps): JSX.Element | null {
    const { question, answer } = door
    if (!question) {
        return null
    }
    if (door.status === 'ready') {
        return (
            <div className="flex flex-col gap-2">
                <p className="m-0 font-medium">{question.prompt}</p>
                <div className="grid grid-cols-2 gap-2">
                    {question.options.map((option) => (
                        <LemonButton
                            key={option.id}
                            type="secondary"
                            fullWidth
                            center
                            data-attr="advent-door-answer"
                            onClick={() => onAnswer(door.id, option.id)}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            </div>
        )
    }
    if (door.status !== 'open' || !answer) {
        return null
    }
    return (
        <div className="flex flex-col gap-0.5 rounded border border-primary bg-surface-secondary p-2 text-xs">
            <span className="text-secondary">{question.prompt}</span>
            <span>
                <span className="text-secondary">Your pick:&nbsp;</span>
                <span className="font-semibold">{answer.label}</span>
            </span>
            <span>{answer.reply}</span>
        </div>
    )
}
