import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCode } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { capitalizeFirstLetter, humanList } from 'lib/utils/strings'

import { DefinitionFile } from './DefinitionFile'
import { ManagedEntityLogicProps, managedEntityLogic } from './managedEntityLogic'
import { kindLabel, ownedFieldLabels } from './managedInCode'
import { openAskForChangeDialog } from './openAskForChangeDialog'

export interface ManagedInCodeBannerProps extends ManagedEntityLogicProps {
    className?: string
}

/** Says that a stack manages this entity, where its definition lives, and which fields are read-only here. */
export function ManagedInCodeBanner({ className, ...props }: ManagedInCodeBannerProps): JSX.Element | null {
    const logic = managedEntityLogic(props)
    const { managedState, binding, ownedFields, detaching } = useValues(logic)
    const { detach } = useActions(logic)

    // Loading and a failed lookup both render nothing: the scene stays usable, and the API still refuses a write.
    if (managedState !== 'managed' || !binding) {
        return null
    }

    const label = kindLabel(props.kind)
    const fieldLabels = ownedFieldLabels(props.kind, ownedFields)

    const confirmDetach = (): void => {
        LemonDialog.open({
            title: `Detach this ${label} from code?`,
            maxWidth: '32rem',
            content: (
                <div className="flex flex-col gap-2">
                    <p className="m-0">
                        The {label} stays in PostHog as it is now. It is no longer managed in code, so every field
                        becomes editable here.
                    </p>
                    <p className="m-0">
                        Unless you remove its definition
                        {binding.source?.file ? (
                            <>
                                {' '}
                                from <code>{binding.source.file}</code>
                            </>
                        ) : null}
                        , the next push from {binding.repository || `the stack ${binding.stack_name}`} will try to
                        create it again.
                    </p>
                </div>
            ),
            primaryButton: {
                children: 'Detach',
                status: 'danger',
                'data-attr': 'managed-in-code-detach-confirm',
                onClick: () => {
                    // pinned: analytics event name, renaming breaks dashboards
                    posthog.capture('managed in code detach confirmed', { kind: props.kind })
                    detach()
                },
            },
            secondaryButton: { children: 'Cancel', 'data-attr': 'managed-in-code-detach-cancel' },
        })
    }

    return (
        <LemonBanner
            type="info"
            icon={<IconCode className="LemonBanner__icon" />}
            className={className}
            alignItems="start"
        >
            <div className="flex flex-col gap-2" data-attr="managed-in-code-banner">
                <div>
                    <strong>Managed in code.</strong> The stack <code>{binding.stack_name}</code> manages this {label}
                    {binding.source?.file ? (
                        <>
                            {' '}
                            from{' '}
                            <DefinitionFile repository={binding.repository} source={binding.source} kind={props.kind} />
                        </>
                    ) : null}
                    {binding.repository ? (
                        <>
                            {' '}
                            in <code>{binding.repository}</code>
                        </>
                    ) : null}
                    .
                </div>
                <div>
                    {fieldLabels.length
                        ? `${capitalizeFirstLetter(humanList(fieldLabels))} ${fieldLabels.length === 1 ? 'is' : 'are'} read-only here. You can still edit everything else.`
                        : `The definition sets no field of this ${label}, so you can edit all of it here.`}
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openAskForChangeDialog({ binding, entryPoint: 'banner' })}
                        data-attr="managed-in-code-ask-for-change"
                    >
                        Ask for a change
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={confirmDetach}
                        loading={detaching}
                        disabledReason={detaching ? 'Detaching…' : undefined}
                        data-attr="managed-in-code-detach"
                    >
                        Detach
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
