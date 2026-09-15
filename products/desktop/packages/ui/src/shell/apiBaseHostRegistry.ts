// Set after authentication because the cloud region is only known at runtime.
let registeredApiBaseHost: string | null = null;

/** Record the backend host used for the current authenticated session. */
export function registerApiBaseHost(host: string | null): void {
  registeredApiBaseHost = host;
}

/** The currently registered backend host, or null if none is registered yet. */
export function getApiBaseHost(): string | null {
  return registeredApiBaseHost;
}
