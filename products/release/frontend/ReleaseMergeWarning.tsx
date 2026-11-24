import { IconWarning } from '@posthog/icons'
import { Text } from '@posthog/quill'

function joined(names: string[]): string {
    return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

export function ReleaseMergeWarning({ deleted }: { deleted: string[] }): JSX.Element {
    return (
        <div
            className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-2"
            data-attr="release-merge-warning"
        >
            <IconWarning className="mt-0.5 size-4 shrink-0 text-destructive-foreground" />
            <Text size="xs" render={<p className="m-0" />}>
                {deleted.length
                    ? `This can't be undone. ${joined(deleted)} ${deleted.length === 1 ? 'is' : 'are'} deleted after the merge.`
                    : "This can't be undone. The merged releases are deleted."}
            </Text>
        </div>
    )
}
