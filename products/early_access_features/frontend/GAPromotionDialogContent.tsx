import { useState } from 'react'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

interface GAPromotionDialogContentProps {
    onChange: (checked: boolean) => void
}

export function GAPromotionDialogContent({ onChange }: GAPromotionDialogContentProps): JSX.Element {
    const [checked, setChecked] = useState(false)
    return (
        <div className="mt-2">
            <LemonCheckbox
                checked={checked}
                onChange={(value) => {
                    setChecked(value)
                    onChange(value)
                }}
                label="Roll out to all users — include users who previously opted out"
                fullWidth
            />
        </div>
    )
}
