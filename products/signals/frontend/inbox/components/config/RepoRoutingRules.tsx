import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'

import type { RepoRoutingRuleApi } from 'products/tasks/frontend/generated/api.schemas'

import { MAX_RULE_TEXT_LENGTH, repoRoutingRulesLogic } from '../../logics/repoRoutingRulesLogic'

const RULES_PAGE_SIZE = 10

interface RuleFieldsProps {
    ruleText: string
    repository: string
    integrationId: number | null
    onRuleTextChange: (ruleText: string) => void
    onRepositoryChange: (repository: string) => void
    onIntegrationIdChange: (integrationId: number | null) => void
    disabled: boolean
}

/** The shared field row for adding and editing a rule: description, org (when several), repository. */
function RuleFields({
    ruleText,
    repository,
    integrationId,
    onRuleTextChange,
    onRepositoryChange,
    onIntegrationIdChange,
    disabled,
}: RuleFieldsProps): JSX.Element {
    const { githubIntegrations } = useValues(integrationsLogic)
    const effectiveIntegrationId = integrationId ?? githubIntegrations[0]?.id

    return (
        <>
            <LemonInput
                size="small"
                className="min-w-0 flex-1"
                placeholder="Which requests match, e.g. anything about the marketing site"
                maxLength={MAX_RULE_TEXT_LENGTH}
                value={ruleText}
                disabledReason={disabled ? 'Saving changes' : undefined}
                onChange={onRuleTextChange}
            />
            {githubIntegrations.length > 1 && (
                <LemonSelect
                    size="small"
                    value={effectiveIntegrationId}
                    disabledReason={disabled ? 'Saving changes' : undefined}
                    options={githubIntegrations.map((integration) => ({
                        value: integration.id,
                        label: integration.display_name,
                    }))}
                    onChange={(next) => onIntegrationIdChange(next)}
                />
            )}
            {effectiveIntegrationId != null && (
                <GitHubRepositoryCombobox
                    integrationId={effectiveIntegrationId}
                    value={repository}
                    disabled={disabled}
                    onChange={(repo) => onRepositoryChange(repo ?? '')}
                    placeholder="Repository"
                />
            )}
        </>
    )
}

function RuleRow({ rule }: { rule: RepoRoutingRuleApi }): JSX.Element {
    const {
        editingRuleId,
        editRuleText,
        editRepository,
        editIntegrationId,
        saveEditedRuleDisabledReason,
        rulesLoading,
    } = useValues(repoRoutingRulesLogic)
    const {
        startEditingRule,
        cancelEditingRule,
        setEditRuleText,
        setEditRepository,
        setEditIntegrationId,
        saveEditedRule,
        deleteRule,
    } = useActions(repoRoutingRulesLogic)
    const { githubIntegrations } = useValues(integrationsLogic)

    if (editingRuleId === rule.id) {
        return (
            <div className="flex flex-wrap items-center gap-1">
                <RuleFields
                    ruleText={editRuleText}
                    repository={editRepository}
                    integrationId={editIntegrationId}
                    onRuleTextChange={setEditRuleText}
                    onRepositoryChange={setEditRepository}
                    onIntegrationIdChange={setEditIntegrationId}
                    disabled={rulesLoading}
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    loading={rulesLoading}
                    disabledReason={saveEditedRuleDisabledReason ?? undefined}
                    onClick={saveEditedRule}
                    data-attr="signals-repo-routing-rule-save"
                >
                    Save
                </LemonButton>
                <LemonButton size="small" onClick={cancelEditingRule}>
                    Cancel
                </LemonButton>
            </div>
        )
    }

    // A stored rule carries only `owner/repo`, so the owning integration is recovered from the owner
    // half. A GitHub integration's display name is the installation's account login, which is that owner.
    const integrationForRule =
        githubIntegrations.find(
            (integration) => integration.display_name.toLowerCase() === rule.repository.split('/')[0].toLowerCase()
        ) ?? null

    return (
        <div className="flex items-center gap-1">
            <span className="text-xs text-default min-w-0 flex-1 truncate" title={rule.rule_text}>
                {rule.rule_text}
            </span>
            <span className="text-xs text-muted shrink-0">{rule.repository}</span>
            {rule.created_by && (
                <Tooltip
                    title={`Added by ${rule.created_by.first_name || rule.created_by.email}${rule.created_by.first_name ? ` (${rule.created_by.email})` : ''}`}
                >
                    <ProfilePicture
                        user={{
                            first_name: rule.created_by.first_name,
                            last_name: rule.created_by.last_name,
                            email: rule.created_by.email,
                        }}
                        size="sm"
                    />
                </Tooltip>
            )}
            <LemonButton
                size="xsmall"
                icon={<IconPencil />}
                aria-label={`Edit routing rule for ${rule.repository}`}
                disabledReason={rulesLoading ? 'Saving changes' : undefined}
                onClick={() => startEditingRule(rule, integrationForRule?.id ?? null)}
                data-attr="signals-repo-routing-rule-edit"
            />
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                aria-label={`Remove routing rule for ${rule.repository}`}
                disabledReason={rulesLoading ? 'Saving changes' : undefined}
                onClick={() => deleteRule(rule)}
                data-attr="signals-repo-routing-rule-delete"
            />
        </div>
    )
}

function AddRuleRow(): JSX.Element {
    const { draftRuleText, draftRepository, draftIntegrationId, addRuleDisabledReason, rulesLoading } =
        useValues(repoRoutingRulesLogic)
    const { setDraftRuleText, setDraftRepository, setDraftIntegrationId, addRule } = useActions(repoRoutingRulesLogic)

    return (
        <div className="flex flex-wrap items-center gap-1">
            <RuleFields
                ruleText={draftRuleText}
                repository={draftRepository}
                integrationId={draftIntegrationId}
                onRuleTextChange={setDraftRuleText}
                onRepositoryChange={setDraftRepository}
                onIntegrationIdChange={setDraftIntegrationId}
                disabled={rulesLoading}
            />
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconPlus />}
                loading={rulesLoading}
                disabledReason={addRuleDisabledReason ?? undefined}
                onClick={addRule}
                data-attr="signals-repo-routing-rule-add"
            >
                Add
            </LemonButton>
        </div>
    )
}

/**
 * CRUD block for the team's repo routing rules, rendered inside the Code access settings
 * section under the GitHub connection it depends on. The same rules the Slack `@PostHog rules`
 * commands manage.
 */
export function RepoRoutingRules(): JSX.Element {
    const { rules, rulesLoading } = useValues(repoRoutingRulesLogic)
    const { githubIntegrations } = useValues(integrationsLogic)
    // Local pagination only: the pager must not write a `page` param into the settings URL.
    const pagination = usePagination(rules ?? [], { pageSize: RULES_PAGE_SIZE, useUrl: false })

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-3">
            <div className="flex flex-col gap-0.5">
                <h4 className="m-0 text-xs font-semibold text-default">Routing rules</h4>
                <p className="m-0 max-w-2xl text-[11px] leading-snug text-tertiary">
                    Steer requests to a repository. When a request matches a rule, agents prefer that rule's repository.
                    Earlier rules win when several match.
                </p>
            </div>
            {rules === null ? (
                rulesLoading ? (
                    <LemonSkeleton className="h-8 w-full rounded" />
                ) : (
                    <p className="m-0 text-xs text-secondary">
                        Couldn't load routing rules. Refresh the page to try again.
                    </p>
                )
            ) : (
                <>
                    {rules.length > 0 && (
                        <div className="flex flex-col gap-1">
                            {pagination.dataSourcePage.map((rule) => (
                                <RuleRow key={rule.id} rule={rule} />
                            ))}
                            <PaginationControl {...pagination} nouns={['rule', 'rules']} />
                        </div>
                    )}
                    {githubIntegrations.length > 0 ? (
                        <AddRuleRow />
                    ) : (
                        <p className="m-0 text-[11px] leading-snug text-tertiary">
                            Connect GitHub above to add a routing rule.
                        </p>
                    )}
                </>
            )}
        </div>
    )
}
