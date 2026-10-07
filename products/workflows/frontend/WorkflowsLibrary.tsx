import { router } from 'kea-router'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MESSAGING_TAB_CONTENT } from './messagingTabs'
import { WorkflowTemplatesBrowser } from './Workflows/templates/WorkflowTemplatesBrowser'

// pinned: URL path segments under /workflows. `library` keeps the email templates it always showed.
export type WorkflowsLibraryTab = 'templates' | 'library'

/** Everything a person reuses: whole workflow templates, and the email templates that steps start from. */
export function WorkflowsLibrary({ tab }: { tab: WorkflowsLibraryTab }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <LemonSegmentedButton<WorkflowsLibraryTab>
                size="small"
                value={tab}
                onChange={(value) => router.actions.push(urls.workflows(value))}
                options={[
                    { value: 'templates', label: 'Workflow templates', 'data-attr': 'workflows-library-templates' },
                    { value: 'library', label: 'Email templates', 'data-attr': 'workflows-library-emails' },
                ]}
            />
            {tab === 'templates' ? <WorkflowTemplatesBrowser /> : MESSAGING_TAB_CONTENT.library}
        </div>
    )
}
