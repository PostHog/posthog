import type { ReactElement } from 'react'
import { Linking, Text } from 'react-native'
import { useProjectScope } from '@/auth/useProjectScope'
import { colors } from '@/ui/tokens'
import { type ObjectRef, objectWebUrl } from './objectTags'

export function ObjectChip({ target }: { target: ObjectRef }): ReactElement {
    const scope = useProjectScope()
    const url = scope && objectWebUrl(scope.host, scope.projectId, target.kind, target.id)
    return (
        <Text
            accessibilityRole={url ? 'link' : undefined}
            style={url ? { color: colors.blue, backgroundColor: colors.sunken } : undefined}
            onPress={
                url
                    ? () => {
                          void Linking.openURL(url).catch(() => undefined)
                      }
                    : undefined
            }
        >
            {target.label}
        </Text>
    )
}
