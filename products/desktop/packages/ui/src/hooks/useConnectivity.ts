import { connectivityStore } from "@posthog/core/connectivity/connectivityStore";
import { createSelectors } from "./createSelectors";

const connectivity = createSelectors(connectivityStore);

export function useConnectivity() {
  return { isOnline: connectivity.use.isOnline() };
}
