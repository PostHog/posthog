import { type ProjectScope, scopeKey } from '@/api/reports'

export const conversationListKeys = {
    all: (scope: ProjectScope | null) => ['classic-conversations', ...scopeKey(scope)] as const,
}
