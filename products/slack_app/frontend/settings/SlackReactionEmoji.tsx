import type { PickerEmoji } from './slackReactionEmojiLogic'

/** One Slack emoji: the workspace's image for a custom emoji, or the character for a standard one. An emoji the
 * picker does not know, such as a custom one the app cannot list, shows nothing, because its name is beside it. */
export function SlackReactionEmoji({
    name,
    emoji,
}: {
    name: string
    emoji: PickerEmoji | undefined
}): JSX.Element | null {
    if (emoji?.imageUrl) {
        return <img src={emoji.imageUrl} alt={`:${name}:`} className="size-5 object-contain" loading="lazy" />
    }
    if (emoji?.character) {
        return (
            <span className="text-lg leading-none" role="img" aria-label={`:${name}:`}>
                {emoji.character}
            </span>
        )
    }
    return null
}
