import { install } from 'undici'

// Node's bundled parser can crash on a paused response at EOF: https://github.com/nodejs/undici/issues/5360.
install()
