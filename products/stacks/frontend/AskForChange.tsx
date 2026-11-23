import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AskForChangeLogicProps, askForChangeLogic } from './askForChangeLogic'
import { DefinitionFile } from './DefinitionFile'
import { fieldLabel, kindLabel } from './managedInCode'

export interface AskForChangeProps extends AskForChangeLogicProps {
    onClose: () => void
}

/** Describe a change to a managed entity. A cloud task edits the definition and opens a pull request. */
export function AskForChange({ onClose, ...props }: AskForChangeProps): JSX.Element {
    const logic = askForChangeLogic(props)
    const { changeRequest, isChangeRequestSubmitting, startedTask, startError, startErrorDetail } = useValues(logic)
    const { setChangeRequestValue } = useActions(logic)
    const { binding, refusedFields = [] } = props
    const repository = binding.repository || `the repository of the stack ${binding.stack_name}`
    const file = binding.source?.file ? (
        <DefinitionFile repository={binding.repository} source={binding.source} kind={binding.kind} />
    ) : (
        'its definition'
    )

    if (startedTask) {
        return (
            <div className="flex flex-col gap-4" data-attr="managed-in-code-change-started">
                <p className="m-0">
                    A task is editing {file} and will open a pull request in <code>{repository}</code>. Nothing changes
                    in PostHog until that pull request is merged and pushed.
                </p>
                <div className="flex flex-wrap justify-end gap-2">
                    <LemonButton type="secondary" onClick={onClose} data-attr="managed-in-code-change-close">
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={startedTask.task_url}
                        onClick={onClose}
                        data-attr="managed-in-code-change-open-task"
                    >
                        Open the task
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <Form logic={askForChangeLogic} props={props} formKey="changeRequest" enableFormOnSubmit>
            <div className="flex flex-col gap-4">
                <p className="m-0">
                    This {kindLabel(binding.kind)} is managed in code. Describe the change, and a task edits {file} in{' '}
                    <code>{repository}</code> and opens a pull request. Nothing changes in PostHog until that pull
                    request is merged and pushed.
                </p>
                <LemonField name="note" label="What should change?">
                    <LemonTextArea
                        placeholder="For example: rename it to Checkout v2 and add the growth tag"
                        minRows={3}
                        maxRows={12}
                        autoFocus
                        data-attr="managed-in-code-change-note"
                    />
                </LemonField>
                {refusedFields.length > 0 && (
                    <LemonField name="values" label="Values you tried to set (optional)">
                        {() => (
                            <div className="flex flex-col gap-2">
                                {refusedFields.map((path) => (
                                    <LemonField.Pure
                                        key={path}
                                        label={capitalizeFirstLetter(fieldLabel(binding.kind, path))}
                                    >
                                        <LemonInput
                                            value={changeRequest.values[path] ?? ''}
                                            onChange={(value) =>
                                                setChangeRequestValue('values', {
                                                    ...changeRequest.values,
                                                    [path]: value,
                                                })
                                            }
                                            data-attr="managed-in-code-change-value"
                                        />
                                    </LemonField.Pure>
                                ))}
                            </div>
                        )}
                    </LemonField>
                )}
                {startError === 'repository_not_connected' ? (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Open integrations',
                            to: urls.settings('environment-integrations', 'integration-github'),
                            'data-attr': 'managed-in-code-change-connect-github',
                        }}
                    >
                        This project has no GitHub connection that can reach <code>{repository}</code>, so a task can't
                        open the pull request. Connect the repository in the GitHub integration and try again, or edit{' '}
                        {file} yourself.
                    </LemonBanner>
                ) : startError === 'tasks_unavailable' ? (
                    <LemonBanner type="warning">
                        This project can't start cloud tasks, so PostHog can't open the pull request. Edit {file} in{' '}
                        <code>{repository}</code> yourself and open a pull request there.
                    </LemonBanner>
                ) : startError === 'other' ? (
                    <LemonBanner type="error">
                        Couldn't start the task. {startErrorDetail ?? 'Try again in a moment.'}
                    </LemonBanner>
                ) : null}
                <div className="flex flex-wrap justify-end gap-2">
                    <LemonButton type="secondary" onClick={onClose} data-attr="managed-in-code-change-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isChangeRequestSubmitting}
                        data-attr="managed-in-code-change-submit"
                    >
                        Start task
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
