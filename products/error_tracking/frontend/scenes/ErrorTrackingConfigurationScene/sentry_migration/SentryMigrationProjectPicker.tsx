import { useActions, useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { sentryMigrationLogic, sentryProjectKey } from './sentryMigrationLogic'

export function SentryMigrationProjectPicker(): JSX.Element {
    const { projects, selectedProjectKey } = useValues(sentryMigrationLogic)
    const { selectProject } = useActions(sentryMigrationLogic)

    return (
        <LemonField.Pure label="Sentry project" className="max-w-sm">
            <LemonInputSelect
                mode="single"
                placeholder="Search projects"
                value={selectedProjectKey ? [selectedProjectKey] : []}
                onChange={(keys) => selectProject(keys[0] ?? null)}
                options={(projects ?? []).map((project) => ({
                    key: sentryProjectKey(project),
                    // The search matches the label, so it carries the organization name too.
                    label: `${project.project_name} (${project.organization_name})`,
                    labelComponent: (
                        <span>
                            <span>{project.project_name}</span>{' '}
                            <span className="text-secondary">{project.organization_name}</span>
                        </span>
                    ),
                }))}
                data-attr="error-tracking-sentry-migration-project"
            />
        </LemonField.Pure>
    )
}
