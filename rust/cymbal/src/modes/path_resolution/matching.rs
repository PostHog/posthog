use std::collections::{BTreeSet, HashMap};

use crate::core::repo_slug::is_valid_repo_path;

pub trait FileSet {
    /// Every file that equals `tail` or ends with `/` + `tail`.
    fn files_ending_with<'a>(&'a self, tail: &str) -> Vec<&'a str>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PathOutcome {
    Sure(String),
    Support(String),
    Tie,
    NoMatch,
}

struct EndMatch<'p> {
    /// The part of the frame path before the matching end.
    stripped: &'p str,
    /// The matching end, shared by the frame path and the files.
    tail: &'p str,
    /// The distinct repo folders that hold a file with that end, sorted.
    added: Vec<String>,
}

pub fn resolve_paths<P: AsRef<str>>(paths: &[P], files: &impl FileSet) -> Vec<PathOutcome> {
    let matches: Vec<Option<EndMatch>> = paths
        .iter()
        .map(|path| longest_end(path.as_ref(), files))
        .collect();

    // Frames whose paths lost the same prefix ran from the same folder, so a sure match tells
    // where the shared-name files of that folder live.
    let mut sure: HashMap<&str, Vec<&str>> = HashMap::new();
    for m in matches.iter().flatten() {
        if let [added] = m.added.as_slice() {
            sure.entry(m.stripped).or_default().push(added);
        }
    }

    matches
        .iter()
        .map(|m| match m {
            None => PathOutcome::NoMatch,
            Some(m) => match m.added.as_slice() {
                [added] => {
                    valid_join(added, m.tail).map_or(PathOutcome::NoMatch, PathOutcome::Sure)
                }
                _ => supported_candidate(m, sure.get(m.stripped).map(Vec::as_slice).unwrap_or(&[]))
                    .and_then(|added| valid_join(added, m.tail))
                    .map_or(PathOutcome::Tie, PathOutcome::Support),
            },
        })
        .collect()
}

fn longest_end<'p>(path: &'p str, files: &impl FileSet) -> Option<EndMatch<'p>> {
    let segment_starts: Vec<usize> = std::iter::once(0)
        .chain(path.match_indices('/').map(|(i, _)| i + 1))
        .collect();
    let segment_count = segment_starts.len();
    for (k, start) in segment_starts.iter().enumerate() {
        let tail = &path[*start..];
        let segment = tail.split('/').next().unwrap_or_default();
        if matches!(segment, "" | "." | "..") {
            continue;
        }
        let hits = files.files_ending_with(tail);
        if hits.is_empty() {
            continue;
        }
        // A file name alone is too weak to choose between several files.
        if segment_count - k < 2 && hits.len() > 1 {
            return None;
        }
        let added: BTreeSet<&str> = hits
            .iter()
            .map(|hit| &hit[..hit.len() - tail.len()])
            .collect();
        return Some(EndMatch {
            stripped: &path[..*start],
            tail,
            added: added.into_iter().map(str::to_string).collect(),
        });
    }
    None
}

fn supported_candidate<'m>(m: &'m EndMatch, votes: &[&str]) -> Option<&'m str> {
    let mut best: Option<(&str, usize)> = None;
    let mut tied = false;
    for candidate in &m.added {
        let count = votes.iter().filter(|vote| **vote == candidate).count();
        match best {
            _ if count == 0 => {}
            Some((_, best_count)) if count < best_count => {}
            Some((_, best_count)) if count == best_count => tied = true,
            _ => {
                best = Some((candidate, count));
                tied = false;
            }
        }
    }
    best.filter(|_| !tied).map(|(candidate, _)| candidate)
}

fn valid_join(added: &str, tail: &str) -> Option<String> {
    let repo_path = format!("{added}{tail}");
    is_valid_repo_path(&repo_path).then_some(repo_path)
}

#[cfg(test)]
mod tests {
    use super::super::file_index::FileIndex;
    use super::*;

    // The expected results come from the reference implementation of the design.
    const REPO: &[&str] = &[
        "apps/web/src/index.tsx",
        "apps/web/src/checkout/cart.ts",
        "apps/admin/src/index.tsx",
        "apps/admin/src/users/table.ts",
        "packages/ui/src/Button.tsx",
        "services/api/manage.py",
        "services/api/acme_api/__init__.py",
        "services/api/acme_api/orders/views.py",
        "services/api/acme_api/billing/invoice.py",
        "services/worker/manage.py",
        "services/worker/acme_worker/__init__.py",
        "services/worker/acme_worker/jobs/email.py",
        "services/api/handlers/cart.go",
        "services/api/handlers/orders.go",
        "services/worker/handlers/orders.go",
        "apps/store/app/models/order.rb",
        "apps/store/app/services/acme/checkout.rb",
        "apps/admin/app/models/order.rb",
        "api/app/Models/Order.php",
        "api/app/Services/CheckoutService.php",
        "admin/app/Models/Order.php",
        "apps/shop/lib/main.dart",
        "apps/shop/lib/src/checkout/cart.dart",
        "rust/crates/checkout/src/payment.rs",
        "rust/crates/api/src/main.rs",
        "feature/billing/src/main/kotlin/com/acme/billing/Invoice.kt",
        "feature/cart/src/main/kotlin/com/acme/cart/CartViewModel.kt",
        "core/src/main/kotlin/com/acme/core/Money.kt",
    ];

    fn sure(path: &str) -> PathOutcome {
        PathOutcome::Sure(path.to_string())
    }

    fn support(path: &str) -> PathOutcome {
        PathOutcome::Support(path.to_string())
    }

    #[test]
    fn resolves_the_reference_vectors() {
        use PathOutcome::{NoMatch, Tie};
        let index = FileIndex::from_text(REPO.join("\n"));
        let requests: Vec<(&str, Vec<(&str, PathOutcome)>)> = vec![
            (
                "python package code",
                vec![
                    ("/app/acme_api/orders/views.py", sure("services/api/acme_api/orders/views.py")),
                    ("/app/acme_api/billing/invoice.py", sure("services/api/acme_api/billing/invoice.py")),
                ],
            ),
            ("python top-level script", vec![("/app/manage.py", NoMatch)]),
            ("python file not in this commit", vec![("/app/acme_api/orders/models.py", NoMatch)]),
            (
                "webpack",
                vec![
                    ("webpack://acme-web/./src/checkout/cart.ts", sure("apps/web/src/checkout/cart.ts")),
                    ("webpack://acme-web/./src/index.tsx", support("apps/web/src/index.tsx")),
                ],
            ),
            ("vite, one shared file", vec![("../../src/index.tsx", Tie)]),
            (
                "vite, shared and unique file",
                vec![
                    ("../../src/index.tsx", support("apps/web/src/index.tsx")),
                    ("../../src/checkout/cart.ts", sure("apps/web/src/checkout/cart.ts")),
                ],
            ),
            (
                "php release folder",
                vec![
                    (
                        "/home/forge/example.com/releases/20260924101500/app/Services/CheckoutService.php",
                        sure("api/app/Services/CheckoutService.php"),
                    ),
                    (
                        "/home/forge/example.com/releases/20260924101500/app/Models/Order.php",
                        support("api/app/Models/Order.php"),
                    ),
                ],
            ),
            (
                "go vanity module",
                vec![
                    ("acme.example.com/shopapi/handlers/cart.go", sure("services/api/handlers/cart.go")),
                    ("acme.example.com/shopapi/handlers/orders.go", support("services/api/handlers/orders.go")),
                ],
            ),
            ("go, shared file only", vec![("acme.example.com/shopapi/handlers/orders.go", Tie)]),
            (
                "rust build path",
                vec![(
                    "/home/runner/work/shop/shop/rust/crates/checkout/src/payment.rs",
                    sure("rust/crates/checkout/src/payment.rs"),
                )],
            ),
            (
                "kotlin, path built from package",
                vec![
                    ("com/acme/billing/Invoice.kt", sure("feature/billing/src/main/kotlin/com/acme/billing/Invoice.kt")),
                    ("com/acme/core/Money.kt", sure("core/src/main/kotlin/com/acme/core/Money.kt")),
                ],
            ),
            ("ruby, shared file only", vec![("/rails/app/models/order.rb", Tie)]),
            (
                "ruby, shared and unique file",
                vec![
                    ("/rails/app/models/order.rb", support("apps/store/app/models/order.rb")),
                    ("/rails/app/services/acme/checkout.rb", sure("apps/store/app/services/acme/checkout.rb")),
                ],
            ),
            (
                "dart package uri",
                vec![
                    ("package:acme_app/src/checkout/cart.dart", sure("apps/shop/lib/src/checkout/cart.dart")),
                    ("package:acme_app/main.dart", sure("apps/shop/lib/main.dart")),
                ],
            ),
            (
                "library frame outside the repo",
                vec![("/usr/local/lib/python3.12/site-packages/django/db/models/base.py", NoMatch)],
            ),
        ];

        for (name, cases) in requests {
            let paths: Vec<&str> = cases.iter().map(|(path, _)| *path).collect();
            let expected: Vec<PathOutcome> =
                cases.into_iter().map(|(_, outcome)| outcome).collect();
            assert_eq!(resolve_paths(&paths, &index), expected, "{name}");
        }
    }
}
