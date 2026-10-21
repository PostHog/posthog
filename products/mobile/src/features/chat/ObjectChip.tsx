import type { ReactElement } from 'react'
import { Text } from 'react-native'
import { useProjectScope } from '@/auth/useProjectScope'
import { useColors } from '@/ui/theme'
import { type ObjectRef, objectWebUrl } from './objectTags'
import { openReplyUrl } from './webLinks'

export function ObjectChip({ target }: { target: ObjectRef }): ReactElement {
    const colors = useColors()
    const scope = useProjectScope()
    const url = scope && objectWebUrl(scope.host, scope.projectId, target.kind, target.id)
    return (
        <Text
            accessibilityRole={url ? 'link' : undefined}
            style={url ? { color: colors.blue, backgroundColor: colors.sunken } : undefined}
            onPress={
                url
                    ? () => {
                          openReplyUrl(url, 'object_chip', { objectKind: target.kind })
                      }
                    : undefined
            }
        >
            {target.label}
        </Text>
    )
}
