import { useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import { IconFlask, IconMegaphone, IconMessage, IconPlus, IconRocket, IconToggle } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ReleaseLinkFlagCombobox } from './ReleaseLinkFlagCombobox'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseRow, ReleaseStage } from './releaseUtils'

type AvatarKind = 'flag' | 'experiment' | 'survey' | 'broadcast' | 'early-access'

const AVATARS: Record<AvatarKind, { color: string; glyph: JSX.Element }> = {
    flag: { color: 'var(--color-product-feature-flags-light)', glyph: <IconToggle /> },
    experiment: { color: 'var(--color-product-experiments-light)', glyph: <IconFlask /> },
    survey: { color: 'var(--color-product-surveys-light)', glyph: <IconMessage /> },
    broadcast: { color: 'var(--color-product-broadcasts-light)', glyph: <IconMegaphone /> },
    'early-access': { color: 'var(--color-product-early-access-features-light)', glyph: <IconRocket /> },
}

const STAGE_AVATAR: Record<ReleaseStage, AvatarKind> = {
    planned: 'flag',
    flag: 'flag',
    experiment: 'experiment',
    early_access: 'early-access',
    released: 'flag',
    ended: 'flag',
}

function NextRow({
    avatar,
    title,
    detail,
    actions,
    dataAttr,
}: {
    avatar: AvatarKind
    title: string
    detail: string
    actions: ReactNode
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex items-start gap-3 py-2.5" data-attr={dataAttr}>
            <IconStack className="mt-0.5 shrink-0">
                <IconStackItem color={AVATARS[avatar].color}>{AVATARS[avatar].glyph}</IconStackItem>
            </IconStack>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <Text size="sm" weight="medium">
                    {title}
                </Text>
                <Text size="xs" variant="muted">
                    {detail}
                </Text>
            </div>
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">{actions}</div>
        </div>
    )
}

function SuggestionRow({
    avatar,
    title,
    detail,
    label,
    to,
    onClick,
    dataAttr,
}: {
    avatar: AvatarKind
    title: string
    detail: string
    label: string
    to?: string
    onClick?: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2.5 py-1" data-attr={dataAttr}>
            <IconStack className="shrink-0 [--icon-stack-size:1.375rem] [--quill-icon-stack-ring:var(--card)] [&_svg]:size-3">
                <IconStackItem color={AVATARS[avatar].color}>{AVATARS[avatar].glyph}</IconStackItem>
            </IconStack>
            <Text size="xs" className="min-w-0 flex-1 truncate">
                <span className="font-medium">{title}</span>
                <span className="text-muted-foreground">{` · ${detail}`}</span>
            </Text>
            <Button
                size="xs"
                variant="link-muted"
                className="shrink-0"
                {...(onClick ? { onClick } : { nativeButton: false, render: <LinkPrimitive to={to ?? ''} /> })}
            >
                {label}
            </Button>
        </div>
    )
}

export function ReleaseNextSteps({ row }: { row: ReleaseRow }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { openSchedule } = useActions(releaseLogic)
    const { relatedSuggestions } = useValues(releaseRelatedLogic)
    const { createReleaseSurvey } = useActions(releaseRelatedLogic)
    const step = row.nextStep
    const surveyFound =
        relatedSuggestions?.releaseId === row.id &&
        relatedSuggestions.items.some((item) => item.kind === 'survey' && item.detected)
    const suggestions = row.suggestions.filter((suggestion) => !(suggestion.key === 'survey' && surveyFound))
    const [showAll, setShowAll] = useState(false)
    const hidden = suggestions.length - 1

    return (
        <div className="flex flex-col border-t border-border pt-3" data-attr="release-next-steps">
            <Text size="xxs" weight="semibold" variant="muted" className="uppercase tracking-wide">
                What's next
            </Text>
            <div className="flex flex-col divide-y divide-border">
                {step ? (
                    <NextRow
                        avatar={STAGE_AVATAR[row.stage]}
                        title={step.title}
                        detail={step.detail}
                        dataAttr="release-next-step-callout"
                        actions={
                            <>
                                {!row.flags.length && canEditReleases && (
                                    <>
                                        <div className="w-56">
                                            <ReleaseLinkFlagCombobox row={row} placeholder="Find a flag" />
                                        </div>
                                        <Button
                                            variant="outline"
                                            nativeButton={false}
                                            render={<LinkPrimitive to={urls.featureFlag('new')} />}
                                            data-attr="release-create-flag"
                                        >
                                            <IconPlus />
                                            Create a flag
                                        </Button>
                                    </>
                                )}
                                {step.secondaryLabel && step.secondaryTo && (
                                    <Button
                                        variant="outline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={step.secondaryTo} />}
                                        data-attr="release-next-step-secondary"
                                    >
                                        {step.secondaryLabel}
                                    </Button>
                                )}
                                {step.label && (
                                    <Button
                                        variant={step.urgent || row.needsDecision ? 'primary' : 'outline'}
                                        {...(step.scheduleFlagId !== undefined
                                            ? { onClick: () => openSchedule(step.scheduleFlagId as number) }
                                            : { nativeButton: false, render: <LinkPrimitive to={step.to ?? ''} /> })}
                                        data-attr="release-next-step"
                                    >
                                        {step.label}
                                    </Button>
                                )}
                            </>
                        }
                    />
                ) : (
                    !suggestions.length && (
                        <Text size="xs" variant="muted" className="py-2.5">
                            Nothing needs a decision right now.
                        </Text>
                    )
                )}
            </div>
            {suggestions.length > 0 && (
                <div className="mt-1 flex flex-col gap-0.5" data-attr="release-suggestions">
                    {(showAll ? suggestions : suggestions.slice(0, 1)).map((suggestion) => (
                        <SuggestionRow
                            key={suggestion.key}
                            avatar={suggestion.key as AvatarKind}
                            title={suggestion.title}
                            detail={suggestion.detail}
                            label={suggestion.label}
                            dataAttr={`release-suggestion-${suggestion.key}`}
                            {...(suggestion.key === 'survey'
                                ? { onClick: () => createReleaseSurvey(row) }
                                : { to: suggestion.to })}
                        />
                    ))}
                    {hidden > 0 && (
                        <Button
                            size="xs"
                            variant="link-muted"
                            className="self-start px-0"
                            onClick={() => setShowAll(!showAll)}
                            data-attr="release-suggestions-more"
                        >
                            {showAll ? 'Show less' : `${hidden} more ${hidden === 1 ? 'idea' : 'ideas'}`}
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}
