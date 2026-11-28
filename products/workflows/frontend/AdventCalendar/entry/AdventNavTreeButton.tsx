import type { CategorySuffixNav } from '~/layout/panel-layout/ProjectTree/CustomCategorySuffix'

import { AdventClassicNavTreeButton } from './AdventClassicNavTreeButton'
import { AdventTodayNavTreeButton } from './AdventTodayNavTreeButton'

export function AdventNavTreeButton({ nav }: { nav: CategorySuffixNav }): JSX.Element {
    return nav === 'today' ? <AdventTodayNavTreeButton /> : <AdventClassicNavTreeButton />
}
