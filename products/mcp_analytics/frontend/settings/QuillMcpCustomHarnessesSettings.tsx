import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { CustomHarnessIcon } from '../components/CustomHarnessIcon'
import type { MCPCustomHarnessApi } from '../generated/api.schemas'
import { mcpCustomHarnessesLogic } from './mcpCustomHarnessesLogic'
import { McpCustomHarnessForm } from './McpCustomHarnessForm'

export function QuillMcpCustomHarnessesSettings({
    onDelete,
}: {
    onDelete: (harness: MCPCustomHarnessApi) => void
}): JSX.Element {
    const { customHarnesses, customHarnessesLoading, editingHarnessId, deletingHarnessId, saveInProgressReason } =
        useValues(mcpCustomHarnessesLogic)
    const { startAddingHarness, startEditingHarness } = useActions(mcpCustomHarnessesLogic)

    return (
        <div className="flex flex-col gap-2" data-attr="mcp-custom-harnesses">
            {editingHarnessId === 'new' ? (
                <McpCustomHarnessForm />
            ) : (
                <Button
                    className="w-full"
                    variant="outline"
                    onClick={startAddingHarness}
                    disabledReason={saveInProgressReason}
                    data-attr="mcp-custom-harness-add"
                >
                    <IconPlus />
                    Add custom harness
                </Button>
            )}

            {customHarnesses === null && customHarnessesLoading ? (
                <>
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                </>
            ) : customHarnesses?.length === 0 && editingHarnessId !== 'new' ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No custom harnesses yet. Add one to name calls from your own clients.
                </Text>
            ) : (
                <ItemGroup className="gap-2">
                    {customHarnesses?.map((harness) =>
                        editingHarnessId === harness.id ? (
                            <McpCustomHarnessForm key={harness.id} />
                        ) : (
                            <Item key={harness.id} variant="outline" size="sm">
                                <ItemMedia>
                                    <CustomHarnessIcon harness={harness.name} />
                                </ItemMedia>
                                <ItemContent className="min-w-0">
                                    <ItemTitle className="truncate" title={harness.name}>
                                        {harness.name}
                                    </ItemTitle>
                                    <ItemDescription className="truncate" title={harness.match_pattern}>
                                        Matches <code>{harness.match_pattern}</code>
                                    </ItemDescription>
                                </ItemContent>
                                <ItemActions>
                                    <Button
                                        size="icon"
                                        tooltip="Edit"
                                        aria-label={`Edit ${harness.name}`}
                                        onClick={() => startEditingHarness(harness)}
                                        disabledReason={saveInProgressReason}
                                        data-attr="mcp-custom-harness-edit"
                                    >
                                        <IconPencil />
                                    </Button>
                                    <Button
                                        size="icon"
                                        tooltip="Delete"
                                        aria-label={`Delete ${harness.name}`}
                                        loading={deletingHarnessId === harness.id}
                                        onClick={() => onDelete(harness)}
                                        data-attr="mcp-custom-harness-delete"
                                    >
                                        <IconTrash />
                                    </Button>
                                </ItemActions>
                            </Item>
                        )
                    )}
                </ItemGroup>
            )}
        </div>
    )
}
