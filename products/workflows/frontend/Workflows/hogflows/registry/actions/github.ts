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
    ],
})
