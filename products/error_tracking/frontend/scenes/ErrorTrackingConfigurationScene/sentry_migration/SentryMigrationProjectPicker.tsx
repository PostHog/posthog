import { useActions, useValues } from 'kea'

import {
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    Field,
    FieldLabel,
} from '@posthog/quill'

import type { SentryProjectApi } from '../../../generated/api.schemas'
import { type SentryOrganizationProjects, sentryMigrationLogic, sentryProjectKey } from './sentryMigrationLogic'

export function SentryMigrationProjectPicker(): JSX.Element {
    const { selectedProject, projectsByOrganization } = useValues(sentryMigrationLogic)
    const { selectProject } = useActions(sentryMigrationLogic)

    return (
        <Field className="w-full max-w-sm">
            <FieldLabel htmlFor="sentry-migration-project">Sentry project</FieldLabel>
            <Combobox
                items={projectsByOrganization}
                value={selectedProject}
                onValueChange={(project: SentryProjectApi | null) =>
                    selectProject(project ? sentryProjectKey(project) : null)
                }
                itemToStringLabel={(project: SentryProjectApi) => project.project_name}
                itemToStringValue={(project: SentryProjectApi) => sentryProjectKey(project)}
                isItemEqualToValue={(project: SentryProjectApi, value: SentryProjectApi) =>
                    sentryProjectKey(project) === sentryProjectKey(value)
                }
            >
                <ComboboxInput
                    id="sentry-migration-project"
                    placeholder="Search projects"
                    data-attr="error-tracking-sentry-migration-project"
                />
                <ComboboxContent>
                    <ComboboxEmpty>No projects match this search.</ComboboxEmpty>
                    <ComboboxList>
                        {(group: SentryOrganizationProjects) => (
                            <ComboboxGroup key={group.value} items={group.items}>
                                <ComboboxLabel>{group.label}</ComboboxLabel>
                                <ComboboxCollection>
                                    {(project: SentryProjectApi) => (
                                        <ComboboxItem key={sentryProjectKey(project)} value={project}>
                                            {project.project_name}
                                        </ComboboxItem>
                                    )}
                                </ComboboxCollection>
                            </ComboboxGroup>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        </Field>
    )
}
