export interface TopicVocabulary {
    topics: {
        heading: string
        newTopic: string
        emptyStateThing: string
        emptyStateDescription: string
        createTopic: string
        deleteTitle: string
        deleteQuestion: string
        deleteConsequence: string
        unsubscribedHeading: string
        transactionalNotice: string
    }
    topicForm: {
        newTitle: string
        editTitle: string
        keyInfo: string
        keyPlaceholder: string
        messageTypeInfo: string
        publicDescriptionHelp: string
        created: string
        updated: string
    }
    topicSelect: {
        label: string
        placeholder: string
        noTopics: string
    }
    unsubscribedList: {
        heading: string
        description: string
        dateColumn: string
        unsubscribe: string
        resubscribe: string
        importTooltip: string
        exportTooltip: string
        noSearchMatches: string
        noneUnsubscribed: (topicName?: string) => string
        pageSummary: (start: number, end: number, count: string) => string
        unsubscribeTitle: (topicName?: string) => string
        importTitle: (topicName?: string) => string
        importDescription: string
        importScope: string
        importScopeAllMarketing: string
        importOtherTopic: string
        importIsSafe: string
        importResult: (added: string, total: string) => string
        added: (identifier: string) => string
        removed: (identifier: string) => string
        addFailed: string
        removeFailed: string
        loadFailed: string
        exportFailed: string
        imported: (count: string) => string
        nothingImported: string
    }
    customerIOImport: {
        description: string
        importStep: string
        csvStep: string
        topicsImported: string
        rerunIsSafe: string
        recipientsWithUnsubscribes: string
        recipientsSkipped: string
        webhookDescription: string
        outboundSyncDescription: string
    }
}

function forTopic(topicName: string | undefined, prefix: string, fallback = ''): string {
    return topicName ? `${prefix}${topicName}` : fallback
}

export const MESSAGE_CATEGORY_WORDS: TopicVocabulary = {
    topics: {
        heading: 'Message categories',
        newTopic: 'New category',
        emptyStateThing: 'category',
        emptyStateDescription:
            'Configure message categories to manage user opt-out preferences for different types of communications.',
        createTopic: 'Create category',
        deleteTitle: 'Delete category',
        deleteQuestion: 'Are you sure you want to delete the message category',
        deleteConsequence: 'All messages associated with this category must be updated manually.',
        unsubscribedHeading: 'Opt-out list',
        transactionalNotice: 'Transactional messages are not eligible for opt-outs',
    },
    topicForm: {
        newTitle: 'New message category',
        editTitle: 'Edit message category',
        keyInfo: 'This is the unique identifier for the category',
        keyPlaceholder: 'e.g., product_updates',
        messageTypeInfo:
            'Marketing messages can be opted out of by users. Transactional messages are not affected by recipient preferences',
        publicDescriptionHelp: 'This description will be shown to users in the email preferences page.',
        created: 'Category created successfully',
        updated: 'Category updated successfully',
    },
    topicSelect: {
        label: 'Message category',
        placeholder: 'Select message type',
        noTopics: 'Configure message categories in the opt-outs section',
    },
    unsubscribedList: {
        heading: 'Marketing opt-out list',
        description: 'Message recipients who have opted out of all marketing messages',
        dateColumn: 'Opt-out date',
        unsubscribe: 'Add opt-out',
        resubscribe: 'Remove opt-out',
        importTooltip: 'Upload a CSV of recipients to opt out',
        exportTooltip: 'Download this opt-out list as a CSV',
        noSearchMatches: 'No opt-outs match your search',
        noneUnsubscribed: (topicName) => `No opt-outs found${forTopic(topicName, ' for ')}`,
        pageSummary: (start, end, count) => `Showing ${start} - ${end} of ${count} opt-outs`,
        unsubscribeTitle: (topicName) => `Add opt-out${forTopic(topicName, ' for ')}`,
        importTitle: (topicName) => `Import opt-outs${forTopic(topicName, ' for ')}`,
        importDescription: 'Bring an opt-out list over from another email tool, or bulk add recipients.',
        importScope: 'Everyone in the file is opted out of',
        importScopeAllMarketing: 'all marketing messages',
        importOtherTopic: 'unless the row names a different category in a',
        importIsSafe:
            "Importing never opts anyone back in, so it's safe to upload the same file twice. A file exported from here imports back as-is.",
        importResult: (added, total) => `Added ${added} opt-outs from ${total} rows.`,
        added: (identifier) => `${identifier} added to opt-out list`,
        removed: (identifier) => `${identifier} removed from opt-out list`,
        addFailed: 'Failed to add opt-out',
        removeFailed: 'Failed to remove opt-out',
        loadFailed: 'Failed to load opt-outs',
        exportFailed: 'Failed to export opt-outs',
        imported: (count) => `Added ${count} opt-outs`,
        nothingImported: 'No opt-outs were added. Check the file and try again.',
    },
    customerIOImport: {
        description: 'Import categories and unsubscribed users from Customer.io.',
        importStep: '1. Import categories & global opt-outs',
        csvStep: '2. Upload opt-out preferences CSV',
        topicsImported: 'Categories imported:',
        rerunIsSafe: 'Safe to rerun, existing categories and users will be updated.',
        recipientsWithUnsubscribes: 'Users with opt-outs:',
        recipientsSkipped: 'Users skipped (no opt-outs):',
        webhookDescription:
            'Configure Customer.io to send a webhook when a user unsubscribes, so PostHog automatically records the opt-out.',
        outboundSyncDescription:
            'When users change their preferences on the PostHog-managed page, automatically sync those changes back to Customer.io. Only categories imported from Customer.io are synced.',
    },
}

export const AUDIENCE_TOPIC_WORDS: TopicVocabulary = {
    topics: {
        heading: 'Topics',
        newTopic: 'New topic',
        emptyStateThing: 'topic',
        emptyStateDescription: 'Create your first topic, or import topics from Customer.io in the More menu.',
        createTopic: 'Create topic',
        deleteTitle: 'Delete topic',
        deleteQuestion: 'Delete the topic',
        deleteConsequence: 'Messages that use this topic need to be updated by hand.',
        unsubscribedHeading: 'Unsubscribed',
        transactionalNotice: "Recipients can't unsubscribe from transactional topics.",
    },
    topicForm: {
        newTitle: 'New topic',
        editTitle: 'Edit topic',
        keyInfo: 'Your app sends preferences by this key. It follows the name until you change it.',
        keyPlaceholder: 'e.g., product-updates',
        messageTypeInfo:
            'Recipients can unsubscribe from marketing topics. Transactional topics ignore recipient preferences.',
        publicDescriptionHelp: 'Recipients see this on their preferences page.',
        created: 'Topic created',
        updated: 'Topic updated',
    },
    topicSelect: {
        label: 'Topic',
        placeholder: 'Select a topic',
        noTopics: 'Create a topic in Audience first',
    },
    unsubscribedList: {
        heading: 'Unsubscribed from all marketing',
        description: 'Recipients who left every marketing topic at once. They still get transactional email.',
        dateColumn: 'Unsubscribed on',
        unsubscribe: 'Unsubscribe recipient',
        resubscribe: 'Resubscribe',
        importTooltip: 'Upload a CSV of recipients to unsubscribe',
        exportTooltip: 'Download this list as a CSV',
        noSearchMatches: 'No unsubscribed recipients match your search',
        noneUnsubscribed: (topicName) => `No one has unsubscribed from ${topicName ?? 'all marketing'}`,
        pageSummary: (start, end, count) => `Showing ${start} - ${end} of ${count} recipients`,
        unsubscribeTitle: (topicName) => `Unsubscribe a recipient from ${topicName ?? 'all marketing'}`,
        importTitle: (topicName) => `Import unsubscribed recipients${forTopic(topicName, ' for ')}`,
        importDescription: 'Bring unsubscribed recipients over from another email tool, or add many at once.',
        importScope: 'Everyone in the file is unsubscribed from',
        importScopeAllMarketing: 'all marketing',
        importOtherTopic: 'unless the row names a different topic in a',
        importIsSafe:
            'Importing never resubscribes anyone, so you can upload the same file twice. A file exported from here imports back as it is.',
        importResult: (added, total) => `Unsubscribed ${added} recipients from ${total} rows.`,
        added: (identifier) => `${identifier} is unsubscribed`,
        removed: (identifier) => `${identifier} is subscribed again`,
        addFailed: "Couldn't unsubscribe the recipient. Try again.",
        removeFailed: "Couldn't resubscribe the recipient. Try again.",
        loadFailed: "Couldn't load unsubscribed recipients. Reload to try again.",
        exportFailed: "Couldn't export the list. Try again.",
        imported: (count) => `Unsubscribed ${count} recipients`,
        nothingImported: 'No one was unsubscribed. Check the file and try again.',
    },
    customerIOImport: {
        description: 'Import topics and unsubscribed recipients from Customer.io.',
        importStep: '1. Import topics and recipients unsubscribed from all marketing',
        csvStep: '2. Upload a CSV of topic preferences',
        topicsImported: 'Topics imported:',
        rerunIsSafe: 'You can run this again. Existing topics and recipients are updated.',
        recipientsWithUnsubscribes: 'Recipients with unsubscribes:',
        recipientsSkipped: 'Recipients skipped (no unsubscribes):',
        webhookDescription:
            'Set up Customer.io to send a webhook when a recipient unsubscribes, so PostHog records it automatically.',
        outboundSyncDescription:
            'When recipients change their preferences on the PostHog-managed page, sync those changes back to Customer.io. Only topics imported from Customer.io are synced.',
    },
}
