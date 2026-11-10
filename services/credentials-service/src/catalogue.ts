// The second bundle entry: print the provider catalogue as JSON for
// `posthog/integrations/catalogue_projection.py`. It never reads the mount or the environment.

import { PROVIDER_SPECS } from './providers'
import { buildCatalogue } from './providers/catalogue'

process.stdout.write(`${JSON.stringify(buildCatalogue(PROVIDER_SPECS), null, 2)}\n`)
