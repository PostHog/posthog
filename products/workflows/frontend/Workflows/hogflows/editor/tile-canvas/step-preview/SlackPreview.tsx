import { TextWithVariables } from './TextWithVariables'

export function SlackPreview({ text, color }: { text: string; color: string }): JSX.Element {
    return (
        <div className="rounded-md border p-2.5 text-left text-[12.5px] leading-snug">
            <div className="whitespace-pre-wrap break-words">
                {text ? (
                    <TextWithVariables text={text} color={color} />
                ) : (
                    <span className="text-secondary">No message yet</span>
                )}
            </div>
        </div>
    )
}
