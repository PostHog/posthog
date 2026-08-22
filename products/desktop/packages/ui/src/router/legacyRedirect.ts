import { redirect } from "@tanstack/react-router";

interface LegacyRedirectTarget {
  /** Canonical destination, e.g. "/loops/$loopId". Params are interpolated
   *  from the legacy route's own params, so same-named params pass through
   *  unchanged. */
  to: string;
  /** Static params for the target (e.g. a fixed settings category) — merged
   *  over the legacy route's own params. */
  params?: Record<string, string>;
  /** Search params to merge over the incoming ones (e.g. a channel the legacy
   *  path used to carry as a segment). Receives the legacy route's params. */
  search?: (
    prev: Record<string, unknown>,
    params: Record<string, string>,
  ) => Record<string, unknown>;
}

/**
 * One pre-standardization URL, kept working forever. The whole legacy surface
 * is built from this: after the URL hierarchy standardization every old route
 * file is a bare `legacyRedirect` call with no component of its own, so there
 * is exactly one rendering of every screen and one redirect mechanism. Old
 * persisted URLs, restored tabs, deep links, and shared links all land here
 * and forward to the canonical path, replacing the history entry so Back
 * never returns to the dead URL. The standardization-era flag worlds both
 * resolve correctly past the redirect: bluebird-off users get bounced to the
 * new-task screen by the root layout's path guard, exactly as before.
 */
export function legacyRedirect(target: LegacyRedirectTarget): {
  beforeLoad: (ctx: {
    params: Record<string, string>;
    search: Record<string, unknown>;
  }) => never;
} {
  return {
    beforeLoad: ({ params, search }) => {
      throw redirect({
        to: target.to,
        params: { ...params, ...target.params } as never,
        search: target.search ? target.search(search, params) : search,
        replace: true,
      });
    },
  };
}
