import { useActions } from 'kea'
import { useId } from 'react'

import { IconGlobe } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'
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

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

const URL_HELP = 'Paste a public page using the site’s final HTTPS address.'
const NAME_HELP = 'Leave blank and PostHog will infer it.'

export const ContentAutopilotSiteFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const id = useId()

    if (todayRailNav) {
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

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <LemonField.Pure label="Site URL" help={URL_HELP}>
                <LemonInput
                    value={draft.domain}
                    onChange={(domain) => setProfileDraft({ domain })}
                    placeholder="https://example.com"
                    prefix={<IconGlobe />}
                    fullWidth
                />
            </LemonField.Pure>
            <LemonField.Pure label="Site name" help={NAME_HELP}>
                <LemonInput
                    value={draft.name}
                    onChange={(name) => setProfileDraft({ name })}
                    placeholder="Example docs"
                    fullWidth
                />
            </LemonField.Pure>
        </div>
    )
}
