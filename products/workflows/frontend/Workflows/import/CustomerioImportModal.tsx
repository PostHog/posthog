import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTable, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { urls } from 'scenes/urls'

import { WorkflowImportResultApi } from 'products/workflows/frontend/generated/api.schemas'

import { customerioImportLogic } from './customerioImportLogic'

const AGENT_PROMPT =
    'Migrate my Customer.io automations to PostHog workflows. Use the migrating-from-customer-io skill: read each ' +
    'automation with the Customer.io MCP, preview the import with workflows-import-customerio, show me the notes, ' +
    'then import them as drafts.'

const CLI_EXAMPLE = `cio api /v1/environments/$ENV_ID/campaigns/$CAMPAIGN_ID > automation.json
cio api /v1/environments/$ENV_ID/templates/$TEMPLATE_ID > template.json`

const STATUS_TAGS: Record<WorkflowImportResultApi['status'], { label: string; type: LemonTagType }> = {
    preview: { label: 'Ready to import', type: 'default' },
    created: { label: 'Draft created', type: 'success' },
    updated: { label: 'Draft updated', type: 'success' },
    skipped: { label: 'Skipped, already enabled', type: 'warning' },
    failed: { label: 'Cannot import', type: 'danger' },
}

export function CustomerioImportModal(): JSX.Element {
    const { isImportModalOpen, campaignCount, files, parseError, results, resultsLoading } =
        useValues(customerioImportLogic)
    const { closeImportModal, setFiles, runImport } = useActions(customerioImportLogic)
    const imported = results && !results.dryRun
    const replacing = !imported ? (results?.results.filter((result) => replacesDraft(result)).length ?? 0) : 0

    return (
        <LemonModal
            isOpen={isImportModalOpen}
            onClose={closeImportModal}
            title="Import from Customer.io"
            description="Bring your Customer.io automations over as draft workflows. Drafts never send until you enable them."
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeImportModal} data-attr="customerio-import-close">
                        {imported ? 'Done' : 'Cancel'}
                    </LemonButton>
                    {!imported && (
                        <>
                            <LemonButton
                                type="secondary"
                                onClick={() => runImport({ dryRun: true })}
                                loading={resultsLoading && !results}
                                disabledReason={
                                    !campaignCount
                                        ? 'Add Customer.io files first'
                                        : resultsLoading
                                          ? 'Working on it'
                                          : undefined
                                }
                                data-attr="customerio-import-preview"
                            >
                                Preview
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => runImport({ dryRun: false })}
                                loading={resultsLoading && !!results}
                                disabledReason={
                                    !campaignCount
                                        ? 'Add Customer.io files first'
                                        : !results
                                          ? 'Preview the import first'
                                          : resultsLoading
                                            ? 'Working on it'
                                            : undefined
                                }
                                data-attr="customerio-import-submit"
                            >
                                Import as drafts
                            </LemonButton>
                        </>
                    )}
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <section className="flex flex-col gap-2">
                    <h4 className="mb-0">Ask your AI agent</h4>
                    <p className="mb-0 text-secondary">
                        With the Customer.io and PostHog MCP servers connected, paste this into your agent. It reads
                        your automations and imports them for you.
                    </p>
                    <CodeSnippet language={Language.Text} wrap thing="prompt">
                        {AGENT_PROMPT}
                    </CodeSnippet>
                </section>
                <section className="flex flex-col gap-2">
                    <h4 className="mb-0">Or upload files from the Customer.io CLI</h4>
                    <p className="mb-0 text-secondary">
                        Save each automation, then add the files here. If you imported opt-outs from Customer.io,
                        PostHog reads the message content with that API key. Otherwise, save the templates its messages
                        use too.
                    </p>
                    <CodeSnippet language={Language.Bash}>{CLI_EXAMPLE}</CodeSnippet>
                    <LemonFileInput
                        accept=".json"
                        multiple
                        value={files}
                        onChange={setFiles}
                        disabledReason={resultsLoading ? 'Wait for the import to finish' : undefined}
                        showUploadedFiles
                        callToAction="Drop .json files here or click to browse"
                    />
                    {parseError ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Clear files',
                                onClick: () => setFiles([]),
                                'data-attr': 'customerio-import-clear-files',
                            }}
                        >
                            {parseError}
                        </LemonBanner>
                    ) : campaignCount ? (
                        <span className="text-secondary" data-attr="customerio-import-count">
                            {campaignCount} {campaignCount === 1 ? 'automation' : 'automations'} found.
                        </span>
                    ) : null}
                </section>
                {results?.content_fetched && (
                    <span className="text-secondary" data-attr="customerio-import-content-fetched">
                        PostHog read the message content from Customer.io with your stored API key.
                    </span>
                )}
                {replacing > 0 && (
                    <LemonBanner type="warning" data-attr="customerio-import-replaces-drafts">
                        {replacing === 1
                            ? 'One automation was imported before. Importing replaces its draft, and edits made to it since are lost.'
                            : `${replacing} automations were imported before. Importing replaces their drafts, and edits made to them since are lost.`}
                    </LemonBanner>
                )}
                {results && (
                    <LemonTable
                        dataSource={results.results}
                        rowKey="source_id"
                        data-attr="customerio-import-results"
                        columns={[
                            {
                                title: 'Automation',
                                key: 'name',
                                render: (_, result) =>
                                    result.workflow_id ? (
                                        <Link to={urls.workflow(result.workflow_id, 'workflow')} target="_blank">
                                            {result.name}
                                        </Link>
                                    ) : (
                                        result.name
                                    ),
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                render: (_, result) =>
                                    replacesDraft(result) ? (
                                        <LemonTag type="warning">Replaces existing draft</LemonTag>
                                    ) : (
                                        <LemonTag type={STATUS_TAGS[result.status].type}>
                                            {STATUS_TAGS[result.status].label}
                                        </LemonTag>
                                    ),
                            },
                            {
                                title: 'Notes',
                                key: 'notes',
                                render: (_, result) =>
                                    result.status === 'failed'
                                        ? result.validation_errors.join(' ')
                                        : summarizeNotes(result),
                            },
                        ]}
                    />
                )}
            </div>
        </LemonModal>
    )
}

function replacesDraft(result: WorkflowImportResultApi): boolean {
    return result.status === 'preview' && !!result.workflow_id
}

function summarizeNotes(result: WorkflowImportResultApi): string {
    const needsInput = result.notes.filter((note) => note.level === 'needs_input').length
    const others = result.notes.length - needsInput
    const parts = [
        needsInput ? `${needsInput} to set before enabling` : null,
        others ? `${others} to review` : null,
    ].filter(Boolean)
    return parts.length ? parts.join(', ') : 'Everything carried over'
}
