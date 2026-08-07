import { Flex, Spinner } from "@radix-ui/themes";

// Default per-route pending UI. TanStack Router renders a route's
// `pendingComponent` (falling back to this) the moment its loader is pending,
// so navigation commits instantly and each route shows a loading state while
// its data resolves. Routes can override `pendingComponent` with a tailored
// skeleton later — this centered spinner is the baseline.
//
// It fills its slot in normal flow (height: 100%) rather than `absolute
// inset-0`: the Outlet's container isn't positioned, so an absolute overlay
// would escape to the viewport and flash over the sidebar/header.
export function RoutePending() {
  return (
    <Flex align="center" justify="center" height="100%" width="100%">
      <Spinner size="3" />
    </Flex>
  );
}
