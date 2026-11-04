import type { ReactElement } from 'react'

import { MoreIcon } from '@/ui/icons/MoreIcon'
import { PillControl } from '@/ui/PillControl'
import { Pressable44 } from '@/ui/Pressable44'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { screenLayout } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import type { ScrollTitle } from '@/ui/useScrollTitle'

interface ViewChromeProps {
    onBack: () => void
    onMore?: () => void
    title?: ScrollTitle
}

export function ViewChrome({ onBack, onMore, title }: ViewChromeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <ScreenChrome
            onBack={onBack}
            backTestID="view-back"
            title={title}
            right={
                <PillControl height={screenLayout.rowHeight}>
                    <Pressable44
                        onPress={() => onMore?.()}
                        disabled={!onMore}
                        accessibilityLabel="More"
                        pressedBackground={colors.background}
                        style={styles.button}
                        testID="view-more"
                    >
                        <MoreIcon size={22} color={onMore ? colors.ink : colors.disabled} />
                    </Pressable44>
                </PillControl>
            }
        />
    )
}

const useStyles = createStyles(() => ({
    button: {
        width: 56,
        height: 36,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
