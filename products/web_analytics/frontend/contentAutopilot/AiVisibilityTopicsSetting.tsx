import { useActions, useValues } from 'kea'

import {
    Button,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { topicLabel } from './aiVisibilityFilters'
import { AiVisibilityTopicMergeDialog } from './AiVisibilityTopicMergeDialog'
import { AiVisibilityTopicRemoveDialog } from './AiVisibilityTopicRemoveDialog'
import { AiVisibilityTopicRenameDialog } from './AiVisibilityTopicRenameDialog'
import { aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'

/** Lists the prompt topics with their prompt counts, and renames, merges and removes them. */
export const AiVisibilityTopicsSetting = (): JSX.Element => {
    const { promptTopics, promptTopicsLoading, promptTopicsError, namedTopics } = useValues(aiVisibilityTopicsLogic)
    const { loadPromptTopics, openTopicDialog } = useActions(aiVisibilityTopicsLogic)
    const rows = promptTopicsError ? [] : (promptTopics ?? [])
    const mergeDisabledReason = namedTopics.length < 2 ? 'There is no other topic to merge into' : undefined

    return (
        <div className="flex flex-col gap-3" data-attr="ai-visibility-topics-setting">
            {promptTopicsError ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadPromptTopics, loading: promptTopicsLoading }}
                >
                    Couldn't load the topics. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : null}
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Topic</TableHead>
                        <TableHead align="right">Prompts</TableHead>
                        <TableHead aria-label="Actions" />
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {promptTopics === null && !promptTopicsError ? (
                        [0, 1, 2].map((row) => (
                            <TableRow key={row}>
                                <TableCell colSpan={3}>
                                    <Skeleton className="h-5 w-full" />
                                </TableCell>
                            </TableRow>
                        ))
                    ) : rows.length === 0 ? (
                        <TableRow>
                            <TableEmpty colSpan={3}>
                                {promptTopicsError
                                    ? 'No topics to show.'
                                    : 'No prompts yet. Add prompts to group them by topic.'}
                            </TableEmpty>
                        </TableRow>
                    ) : (
                        rows.map(({ topic, prompts }) => (
                            <TableRow key={topic || 'no-topic'}>
                                <TableCell>
                                    <Text
                                        size="xs"
                                        variant={topic ? 'default' : 'muted'}
                                        weight={topic ? 'semibold' : 'normal'}
                                        render={<span />}
                                    >
                                        {topicLabel(topic)}
                                    </Text>
                                </TableCell>
                                <TableCell align="right">
                                    <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
                                        {pluralize(prompts, 'prompt')}
                                    </Text>
                                </TableCell>
                                <TableCell>
                                    {topic ? (
                                        <div className="flex justify-end gap-1">
                                            <Button
                                                size="sm"
                                                onClick={() => openTopicDialog('rename', topic)}
                                                data-attr="ai-visibility-topic-rename"
                                            >
                                                Rename
                                            </Button>
                                            <Button
                                                size="sm"
                                                onClick={() => openTopicDialog('merge', topic)}
                                                disabledReason={mergeDisabledReason}
                                                data-attr="ai-visibility-topic-merge"
                                            >
                                                Merge
                                            </Button>
                                            <Button
                                                size="sm"
                                                onClick={() => openTopicDialog('remove', topic)}
                                                data-attr="ai-visibility-topic-remove"
                                            >
                                                Remove
                                            </Button>
                                        </div>
                                    ) : null}
                                </TableCell>
                            </TableRow>
                        ))
                    )}
                </TableBody>
            </Table>
            <AiVisibilityTopicRenameDialog />
            <AiVisibilityTopicMergeDialog />
            <AiVisibilityTopicRemoveDialog />
        </div>
    )
}
