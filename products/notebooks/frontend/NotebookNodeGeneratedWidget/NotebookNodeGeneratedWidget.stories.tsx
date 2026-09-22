import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { notebookTestTemplate } from 'scenes/notebooks/Notebook/__mocks__/notebook-template-for-snapshot'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { MarkdownNotebookV2 } from 'scenes/notebooks/Notebook/MarkdownNotebookV2Renderer'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { mswDecorator } from '~/mocks/browser'

const shortId = 'widget-generation'
const notebook = {
    ...notebookTestTemplate('Widget generation', []),
    short_id: shortId,
    content: buildMarkdownNotebookContent(
        '# Widget generation\n\n<Widget showFilters showResults nodeId="chart" prompt="Create an interactive bar chart" />'
    ),
}

function WidgetNotebook(): JSX.Element {
    const logic = useMountedLogic(notebookLogic({ shortId, mode: 'notebook' }))
    const { clearLocalContent, loadNotebook, setEditable } = useActions(logic)
    useEffect(() => {
        clearLocalContent()
        loadNotebook()
        setEditable(true)
    }, [clearLocalContent, loadNotebook, setEditable])
    return (
        <BindLogic logic={notebookLogic} props={logic.props}>
            <div className="max-w-3xl mx-auto p-4">
                <MarkdownNotebookV2 />
            </div>
        </BindLogic>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Notebooks/Generated widgets',
    component: WidgetNotebook,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.NOTEBOOK_GENERATED_WIDGETS],
        testOptions: {
            waitForSelector: '[data-attr="notebook-generated-widget-run-button"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/widget-generation': notebook,
                '/api/projects/:team_id/notebooks/widget-generation/widgets/chart/status': {
                    lifecycle_status: 'awaiting_generation',
                    has_versions: false,
                    active_job: null,
                    artifact_url: null,
                    error_detail: null,
                    current_version_id: null,
                    pinned_version_id: null,
                    frame_names: [],
                    input_bindings: {},
                    input_contract: [],
                    security_review: null,
                    is_reusable: false,
                    build_hash: null,
                },
            },
        }),
    ],
}

export default meta
type Story = StoryObj<typeof meta>

export const BeforeGeneration: Story = {}
