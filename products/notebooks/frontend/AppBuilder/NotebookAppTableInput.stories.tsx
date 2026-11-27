import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { TableDraft } from './notebookAppTableDraftsLogic'
import { NotebookAppTableInput } from './NotebookAppTableInput'

const meta: Meta<typeof NotebookAppTableInput> = {
    title: 'Scenes-App/Notebooks/Table input',
    component: NotebookAppTableInput,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const Targets: StoryObj<typeof NotebookAppTableInput> = {
    render: () => {
        const [draft, setDraft] = useState<TableDraft>()
        const [values, setValues] = useState<Record<string, string[]>>({
            segment: ['Self-serve', 'Teams'],
            activation_target: ['25', '40'],
        })
        return (
            <NotebookAppTableInput
                key={JSON.stringify(values)}
                title="Activation targets"
                columns={Object.entries(values).map(([name, list]) => ({ name, values: list }))}
                draft={draft}
                onDraftChange={setDraft}
                disabled={false}
                onApply={setValues}
            />
        )
    },
}
