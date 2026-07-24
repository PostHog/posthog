// Shared Vitest test options for Trunk Flaky Tests uploads. Imported and spread
// into each package's `test` block so the junit reporter and retry policy stay
// defined in one place. See the upload steps in .github/workflows/test.yml.
//
// `outputFile` is relative, so each config writes ./junit.xml next to itself;
// CI globs apps/*/junit.xml and packages/*/junit.xml. The explicit type keeps
// the reporter tuple assignable across the Vitest 2.x and 4.x versions in use.
export const trunkTestOptions: {
  retry: number;
  reporters: (string | [string, Record<string, unknown>])[];
} = {
  // Disable retries so flaky-test detection sees raw pass/fail results.
  retry: 0,
  reporters: [
    "default",
    ["junit", { outputFile: "./junit.xml", addFileAttribute: true }],
  ],
};
