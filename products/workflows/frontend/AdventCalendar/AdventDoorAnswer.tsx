import { LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { AdventDoor } from './adventGraph'

export interface AdventDoorAnswerProps {
    door: AdventDoor
    shares?: Record<string, number>
    onAnswer: (doorId: string, optionId: string) => void
}

export function AdventDoorAnswer({ door, shares, onAnswer }: AdventDoorAnswerProps): JSX.Element | null {
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
            {shares && (
                <div className="mt-1 flex flex-col gap-1" data-attr="advent-door-shares">
                    <span className="text-secondary">How people answered</span>
                    {question.options.map((option) => (
                        <div key={option.id} className="flex items-center gap-2">
                            <span className="w-24 shrink-0 truncate">{option.label}</span>
                            <LemonProgress className="flex-1" percent={shares[option.id] ?? 0} />
                            <span className="w-9 shrink-0 text-right font-semibold tabular-nums">
                                {`${shares[option.id] ?? 0}%`}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
