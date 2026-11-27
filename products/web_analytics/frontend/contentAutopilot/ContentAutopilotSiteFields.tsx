import { useActions } from 'kea'
import { useId } from 'react'

import { IconGlobe } from '@posthog/icons'
import {
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
} from '@posthog/quill'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

const URL_HELP = 'Paste a public page using the site’s final HTTPS address.'
const NAME_HELP = 'Leave blank and PostHog will infer it.'

export const ContentAutopilotSiteFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)
    const id = useId()

    return (
        <div className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2">
            <Field>
                <FieldLabel htmlFor={`${id}-url`}>Site URL</FieldLabel>
                <InputGroup>
                    <InputGroupAddon align="inline-start">
                        <InputGroupText>
                            <IconGlobe />
                        </InputGroupText>
                    </InputGroupAddon>
                    <InputGroupInput
                        id={`${id}-url`}
                        value={draft.domain}
                        onChange={(event) => setProfileDraft({ domain: event.target.value })}
                        placeholder="https://example.com"
                    />
                </InputGroup>
                <FieldDescription>{URL_HELP}</FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-name`}>Site name</FieldLabel>
                <Input
                    id={`${id}-name`}
                    value={draft.name}
                    onChange={(event) => setProfileDraft({ name: event.target.value })}
                    placeholder="Example docs"
                />
                <FieldDescription>{NAME_HELP}</FieldDescription>
            </Field>
        </div>
    )
}
