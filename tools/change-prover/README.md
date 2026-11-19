# Change prover

The change prover is the one publisher of proofs that stamphog reads.
Each kind of claim is a lane, and each lane posts its own check run:

- The dependency lane posts `Dependency proof`.
- The revert lane posts `Revert proof`.

All lanes use one GitHub App, one `dependency-proof` environment and one `issuer.yml`.
Each lane marks its proof with the same `stamphog:v1` marker.
A proof lifts a deny category only when a `.stamphog/policy.yml` attestation entry names its check.
That entry, and not the prover, decides what the proof lifts and for which paths.

## What the dependency proof proves

The prover checks a dependency update that a bot opened, and it does not trust the bot's result.
It replays the update with pnpm, starting from the merge base of the pull request.
It then compares the lockfile that the replay writes with the lockfile at the pull request head.
It also scans each package that the update adds with GuardDog.
When the lockfiles are equal and the scan is clean, it posts the `Dependency proof` check run on the head commit.
The check names each file it proved.
stamphog can then lift the `deps_toolchain` deny category for those files, and for no other file.

The proof covers a narrow class of change.
The pull request must come from Renovate and change only `package.json`, `pnpm-lock.yaml` and `pnpm-workspace.yaml` files.
Each version must move up without a breaking change, and each new release must be at least seven days old.
Every pnpm settings file must equal the default branch's copy.
The core refuses anything outside this class, and a refusal lifts nothing.

## What the revert proof proves

The revert proof shows that a pull request is a clean revert of one commit on the default branch, and holds nothing else.
Any author may open the pull request, because the proof is about the content.
The head branch must be in this repository, and the author must have pushed the head, so nobody can put a revert onto another author's pull request, such as a bot's.

`revert-proof-trigger.yml` runs its job only when the pull request title starts with `Revert`.
`revert-proof.yml` then runs four jobs, with the same permissions as the dependency lane:

- `identify` finds the open pull request at the head and its merge base through the API. It reads the `This reverts commit <sha>.` lines of the pull request's own commits. No such line means nothing to attest. Two or more different commits are refused.
- `identify` also checks the reverted commit. It must be an ancestor of the merge base, and a merged pull request must have landed it on the default branch as its merge commit. That pull request must be merged no more than 30 days before the proof runs.
- `prove` fetches the merge base, the head, the reverted commit and its parent without a credential. It refuses a reverted commit that is a merge commit, a root commit, or a revert itself. It then runs `git merge-tree --write-tree --merge-base=<reverted> <merge base> <parent>`, which is the merge that `git revert` does. A conflict is refused. The result tree must equal the head tree.
- `conclude` decides the `Revert proof` check run, without a token, and `publish` posts it. The proof names each file that the revert changes.

A merge of the default branch into the pull request is allowed, because the tree comparison proves the content.
git reads no `.gitattributes` for the merge, so a file in the pull request cannot select a merge driver such as `union` that hides a conflict.

The 30-day window is a staleness check, not a security control.
Later code builds on an old commit, and a revert can break that code without a conflict.
The window counts from the time of the run and from the merge time that GitHub records, because an author can set a commit time to any value.

The proof does not show that the revert is safe.
It shows that the content is a clean revert, and nothing about what the revert does.
A revert of a security fix brings the vulnerability back, and a revert of a migration can lose data or break the schema.
So the policy entry must not let a revert lift deny categories such as `migrations` or `auth`.

## How it runs

Two workflows split the work.

- `dependency-proof-trigger.yml` runs on `pull_request` when a dependency file changes. It has no permissions and runs one empty step. It only starts the second workflow.
- `dependency-proof.yml` runs on `workflow_run`. GitHub runs it from the default-branch copy, so a pull request cannot change the workflow that judges it.

| Job        | Permission                                                        | Work                                                                                                           |
| ---------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `identify` | `contents: read`, `pull-requests: read`                           | Finds the one open pull request at the head by an allowed author, checks the pusher, and reads the merge base. |
| `prove`    | none                                                              | Replays pnpm in a merge-base worktree with `--lockfile-only`, `--ignore-scripts` and `--ignore-pnpmfile`.      |
| `scan`     | none                                                              | Scans the added packages with GuardDog.                                                                        |
| `conclude` | none                                                              | Runs `conclude`, which decides the check run from the other jobs' results.                                     |
| `publish`  | none, plus an App token with `checks: write` from its environment | Posts the check run that `conclude` decided.                                                                   |

Only `publish` can reach the App key, and `publish` checks out nothing and runs only `gh`.

Nothing from the pull request tree runs.
Each job checks out only the prover, the `setup-uv` action and `.nvmrc` from the default branch.
The prover reads the head from the git object database and writes its dependency files into a merge-base worktree as data.
The pnpm version comes from the merge base, and the settings come from the default branch.

The proof pins the code it ran.
`issuer.yml` is the prover's own manifest: it lists every path the workflows run from.
A path that ends in `/` is a directory, so a new file in the package is covered without an edit.
The proof reports the tree SHA of each listed directory and the blob SHA of each listed file, at the workflow commit.
It also reports the blob SHA of each pnpm settings file it read.
`.stamphog/policy.yml` names the manifest as `issuer` on the `dependency_proof` attestation, and holds no copy of the list.
The policy keeps only who may attest (the check name and the App) and what the proof may lift.
stamphog reads the manifest from the default branch, and accepts a proof only when the proof pins every listed path, and only while the default branch still holds each pinned object.
A proof made by an older prover, or under older settings, therefore lifts nothing.
`tests/test_package.py` fails when a path the workflows check out or run is not covered by `issuer.yml`.

Every decision lives in a pure core.
`change_prover/core/` holds pure functions over plain values, and every refusal is raised there.
`prove.py`, `scan.py` and `cli.py` are the shell: they read git, the GitHub API and the registry, and they run pnpm.
The shell may interleave reads and checks, but it never decides.
`tests/test_package.py` keeps side-effecting modules out of the core.
A refusal is an answer: the check is neutral and the run passes.
A broken prover also gives a neutral check, but the run fails so that the failure is visible.

## Design principles and where they come from

**The verifier recomputes the result.**
Proof-carrying code moves trust from the producer to a small checker, because even trusted authors "can make errors occasionally or even act maliciously" [1].
Translation validation checks each compiler run instead of the whole compiler [2], reproducible builds let any party rebuild the same bits [3], and Chromium's Rubber Stamper approves only changes it can verify [4].
The prover follows the same rule: it replays the update and compares bytes.

**The verifier picks its own tools.**
Source review cannot protect against a subverted toolchain [5], and diverse double-compiling works because the defender chooses the trusted compiler [6].
So the pnpm version, the settings and the prover code never come from the pull request.

**Identity names the process, not the content.**
SLSA provenance and in-toto keys say which process ran a step, and in-toto checks what the step produced with separate rules [7] [8].
TUF gives each key a narrow role and keeps automated keys out of the roles that clients trust most [9].
Here the Renovate account admits a pull request and the App identity names the pinned prover, but only the replay shows that the lockfile is correct.

**The checker comes from the default branch.**
SLSA Build L3 keeps signing material out of reach of the steps that a tenant controls [7].
The `workflow_run` split and the pinned blobs give the same property: a pull request cannot edit its judge or reach the key.

**Fail closed, and prove every file.**
In the Clark-Wilson model, a procedure that takes unchecked input must make it valid or reject it [10], and KeyNote assertions are monotonic, so a missing credential can only lower the result [11].
The prover refuses the whole update when one file is outside the class.
stamphog's `every_file_attested` gate refuses a bot pull request unless a pinned proof covers every file, and it waits while the check is pending.

**Nothing lifts itself.**
Clark-Wilson separation of duty says that an agent who can certify an entity may not execute it [10].
The prover accepts only dependency files, so a change to the prover cannot prove itself, and the `stamphog_policy` deny category sends changes to the prover, its workflows and the policy to a person.

**Author trust only admits or restricts. Evidence approves.**
Only about 15% of review comments point to a possible defect [12], but lower review coverage links to more post-release defects [13], so a lane may drop human review only where a check does that work.
The xz-utils backdoor shipped in the release tarballs of a widely trusted project [14], from an account that had earned maintainer trust over years.
Reputation can be built up on purpose, so the bot account only admits the change and the proof approves it.

**Same-family review is not independent.**
Programs written independently from one specification still fail on the same inputs more often than independence predicts, and models from one family share even more errors.
The replay fails in a different way from a model review, which is why it can carry the approval.

## Limits

- The proof shows that the head lockfile is what pnpm writes for the manifests. It does not show that the new upstream code is safe or behaves the same. A malicious release from a real maintainer passes the replay.
- The seven-day release age and the GuardDog scan lower that risk. GuardDog uses heuristics, so a clean scan is not a proof of safety.
- The pinned files are not the whole build. The runner image, Node from `setup-node`, the pnpm package from the registry, the pinned GitHub Actions and GuardDog's dependencies are trusted, not proved.
- The replay writes the lockfile only. It runs no install scripts and no tests, so it says nothing about whether the code still builds or passes tests.
- The lift covers `deps_toolchain` on the proved files only. Every other deny category still applies.
- The proof replays against the live registry. A registry change after the head commit can make the replay differ, and the prover then refuses.

## References

1. G. C. Necula. "Proof-Carrying Code." POPL 1997, pp. 106-119. https://doi.org/10.1145/263699.263712
2. G. C. Necula. "Translation Validation for an Optimizing Compiler." PLDI 2000, pp. 83-94. https://doi.org/10.1145/349299.349314
3. Reproducible Builds project. "Definitions." https://reproducible-builds.org/docs/definition/
4. Chromium. "Rubber Stamper" README. https://chromium.googlesource.com/infra/infra/+/HEAD/go/src/infra/appengine/rubber-stamper/README.md
5. K. Thompson. "Reflections on Trusting Trust." Communications of the ACM 27(8), 1984, pp. 761-763. https://doi.org/10.1145/358198.358210
6. D. A. Wheeler. "Countering Trusting Trust through Diverse Double-Compiling." ACSAC 2005, pp. 33-48. https://doi.org/10.1109/CSAC.2005.17 (preprint: https://arxiv.org/abs/1004.5548)
7. SLSA. "Security levels," specification v1.1. https://slsa.dev/spec/v1.1/levels
8. S. Torres-Arias, H. Afzali, T. K. Kuppusamy, R. Curtmola and J. Cappos. "in-toto: Providing farm-to-table guarantees for bits and bytes." USENIX Security 2019. https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias
9. The Update Framework specification. https://theupdateframework.github.io/specification/latest/
10. D. D. Clark and D. R. Wilson. "A Comparison of Commercial and Military Computer Security Policies." IEEE Symposium on Security and Privacy, 1987, pp. 184-194. https://doi.org/10.1109/SP.1987.10001
11. M. Blaze, J. Feigenbaum, J. Ioannidis and A. Keromytis. "The KeyNote Trust-Management System Version 2." RFC 2704, 1999. https://www.rfc-editor.org/rfc/rfc2704.html
12. J. Czerwonka, M. Greiler and J. Tilford. "Code Reviews Do Not Find Bugs: How the Current Code Review Best Practice Slows Us Down." ICSE 2015 (SEIP), pp. 27-28. https://doi.org/10.1109/ICSE.2015.131
13. S. McIntosh, Y. Kamei, B. Adams and A. E. Hassan. "The Impact of Code Review Coverage and Code Review Participation on Software Quality: A Case Study of the Qt, VTK, and ITK Projects." MSR 2014, pp. 192-201. https://doi.org/10.1145/2597073.2597076
14. CVE-2024-3094, malicious code in the xz upstream tarballs. https://www.cve.org/CVERecord?id=CVE-2024-3094
