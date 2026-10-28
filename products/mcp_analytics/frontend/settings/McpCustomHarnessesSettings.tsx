import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { mcpCustomHarnessesLogic } from './mcpCustomHarnessesLogic'

export function McpCustomHarnessesSettings(): JSX.Element {
    const { customHarnesses, customHarnessesLoading, isNewCustomHarnessSubmitting } = useValues(mcpCustomHarnessesLogic)
    const { deleteCustomHarness } = useActions(mcpCustomHarnessesLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonTable
                dataSource={customHarnesses ?? []}
                loading={customHarnessesLoading}
                emptyState="No custom harnesses yet. Add one to name calls from your own clients."
                columns={[
                    { title: 'Name', dataIndex: 'name' },
                    { title: 'Matches', dataIndex: 'match_pattern' },
                    {
                        width: 0,
                        render: (_, harness) => (
                            <LemonButton
                                size="small"
                                status="danger"
                                onClick={() => deleteCustomHarness(harness.id)}
                                data-attr="mcp-custom-harness-delete"
                            >
                                Delete
                            </LemonButton>
                        ),
                    },
                ]}
            />
            <Form logic={mcpCustomHarnessesLogic} formKey="newCustomHarness" enableFormOnSubmit>
                <div className="flex flex-wrap items-end gap-2">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Acme agent" maxLength={100} />
                    </LemonField>
                    <LemonField
                        name="match_pattern"
                        label="Client name contains"
                        help="Not case sensitive. Matches the client name or User-Agent product the harness reports."
                    >
                        <LemonInput placeholder="acme-agent" maxLength={100} />
                    </LemonField>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isNewCustomHarnessSubmitting}
                        data-attr="mcp-custom-harness-add"
                    >
                        Add harness
                    </LemonButton>
                </div>
            </Form>
        </div>
    )
}
