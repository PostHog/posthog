const PACKAGE_PATH = /^\/((?:@[^/]+\/)?[^/@]+)@([^/]+)(.*)$/;
const EXACT_VERSION = /^\d+\.\d+\.\d+(?:-[\w.-]+)?$/;

export function pinSketchpadModuleUrl(value, resolvedPath) {
  const url = new URL(value);
  if (url.hostname !== "esm.sh") return value;
  const requested = decodeURI(url.pathname).match(PACKAGE_PATH);
  if (!requested || EXACT_VERSION.test(requested[2])) return value;
  const resolved = resolvedPath?.match(PACKAGE_PATH);
  if (
    !resolved ||
    resolved[1] !== requested[1] ||
    !EXACT_VERSION.test(resolved[2])
  ) {
    throw new Error(`Cannot pin the resolved module version for ${value}`);
  }
  url.pathname = `/${requested[1]}@${resolved[2]}${requested[3]}`;
  return url.href;
}
