import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton } from '@posthog/lemon-ui'

import { mcpCustomHarnessesLogic } from './mcpCustomHarnessesLogic'
import { McpCustomHarnessForm } from './McpCustomHarnessForm'

export function McpCustomHarnessesSettings(): JSX.Element {
    const { customHarnesses, customHarnessesLoading, editingHarnessId, deletingHarnessId } =
        useValues(mcpCustomHarnessesLogic)
    const { startAddingHarness, startEditingHarness, deleteCustomHarness } = useActions(mcpCustomHarnessesLogic)

    return (
        <div className="flex flex-col gap-2" data-attr="mcp-custom-harnesses">
            {editingHarnessId === 'new' ? (
                <McpCustomHarnessForm />
            ) : (
                <LemonButton
                    className="w-full"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={startAddingHarness}
                    data-attr="mcp-custom-harness-add"
                >
                    Add custom harness
                </LemonButton>
            )}

            {customHarnesses === null && customHarnessesLoading ? (
                <LemonSkeleton className="h-10" repeat={2} />
            ) : customHarnesses?.length === 0 && editingHarnessId !== 'new' ? (
                <p className="text-secondary m-0">
                    No custom harnesses yet. Add one to name calls from your own clients.
                </p>
            ) : (
                customHarnesses?.map((harness) =>
                    editingHarnessId === harness.id ? (
                        <McpCustomHarnessForm key={harness.id} />
                    ) : (
                        <div
                            key={harness.id}
                            className="border rounded flex items-center gap-2 p-2 pl-4 bg-surface-primary"
                        >
                            <span className="flex-1 min-w-0 truncate font-semibold" title={harness.name}>
                                {harness.name}
                            </span>
                            <span className="flex-1 min-w-0 truncate text-secondary" title={harness.match_pattern}>
                                Matches <code>{harness.match_pattern}</code>
                            </span>
                            <div className="flex gap-1 shrink-0">
                                <LemonButton
                                    icon={<IconPencil />}
                                    tooltip="Edit"
                                    aria-label={`Edit ${harness.name}`}
                                    onClick={() => startEditingHarness(harness)}
                                    data-attr="mcp-custom-harness-edit"
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    tooltip="Delete"
                                    aria-label={`Delete ${harness.name}`}
                                    loading={deletingHarnessId === harness.id}
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: `Delete ${harness.name}?`,
                                            description:
                                                'Calls from this client go back to the built-in harness names.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Delete',
                                                onClick: () => deleteCustomHarness(harness.id),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }
                                    data-attr="mcp-custom-harness-delete"
                                />
                            </div>
                        </div>
                    )
                )
            )}
        </div>
    )
}
