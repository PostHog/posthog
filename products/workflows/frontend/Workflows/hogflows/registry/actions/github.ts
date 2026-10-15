import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({
    label: 'GitHub',
    nodes: [
        {
            type: 'function',
            name: 'Find comment',
            description: 'Check if an issue or pull request has a comment that contains some text.',
            config: { template_id: 'template-github-find-comment', inputs: {} },
            output_variable: { key: 'github_comment_found', result_path: 'found', label: 'Comment found' },
        },
        {
            type: 'function',
            name: 'Add comment',
            description: 'Post a comment on an issue or pull request.',
            config: { template_id: 'template-github-create-comment', inputs: {} },
        },
        {
            type: 'function',
            name: 'Get pull request',
            description: "Fetch a pull request's state, branches, and labels into workflow variables.",
            config: { template_id: 'template-github-get-pull-request', inputs: {} },
            output_variable: [
                { key: 'github_pr_number', result_path: 'number', label: 'PR number' },
                { key: 'github_pr_title', result_path: 'title', label: 'PR title' },
                { key: 'github_pr_state', result_path: 'state', label: 'PR state' },
                { key: 'github_pr_draft', result_path: 'draft', label: 'PR is draft' },
                { key: 'github_pr_merged', result_path: 'merged', label: 'PR is merged' },
                { key: 'github_pr_author', result_path: 'author', label: 'PR author' },
                { key: 'github_pr_head_ref', result_path: 'head_ref', label: 'PR head branch' },
                { key: 'github_pr_head_sha', result_path: 'head_sha', label: 'PR head commit' },
                { key: 'github_pr_base_ref', result_path: 'base_ref', label: 'PR base branch' },
                { key: 'github_pr_html_url', result_path: 'html_url', label: 'PR URL' },
                { key: 'github_pr_labels', result_path: 'labels', label: 'PR labels' },
            ],
        },
        {
            type: 'function',
            name: 'Update issue or PR',
            description: 'Close, reopen, or edit the title or body of an issue or pull request.',
            config: { template_id: 'template-github-update-issue', inputs: {} },
        },
    ],
})
