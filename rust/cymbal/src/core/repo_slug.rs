//! Repo slugs name the stored file list of a repository, for example `github.com/acme/shop`.
//! Django writes the list under the slug, and cymbal reads it back under the same slug.
//! `products/error_tracking/backend/logic/repo_paths/slug.py` parses remote URLs the same way,
//! and both run the cases in `tests/static/repo_slug_cases.json`.

const URL_SCHEMES: [&str; 3] = ["https://", "http://", "ssh://"];

/// The slug of a git remote URL: `https://`, `http://`, `ssh://` or `user@host:path` forms.
pub fn parse_repo_slug(remote_url: &str) -> Option<String> {
    let url = remote_url.trim();
    if url.is_empty()
        || url
            .chars()
            .any(|c| c.is_whitespace() || c == '?' || c == '#')
    {
        return None;
    }

    let lowered = url.to_ascii_lowercase();
    let (host, path) = match URL_SCHEMES
        .iter()
        .find(|scheme| lowered.starts_with(**scheme))
    {
        Some(scheme) => {
            let (authority, path) = url[scheme.len()..].split_once('/')?;
            let host_port = authority.rsplit('@').next().unwrap_or(authority);
            (host_port.split(':').next().unwrap_or(host_port), path)
        }
        None => {
            let (user, rest) = url.split_once('@')?;
            let (host, path) = rest.split_once(':')?;
            if user.is_empty() || user.contains(['/', ':']) || host.contains(['@', '/']) {
                return None;
            }
            (host, path)
        }
    };

    let path = path.trim_end_matches('/');
    let path = path.strip_suffix(".git").unwrap_or(path);
    let path = path.strip_prefix('/').unwrap_or(path);
    let slug = format!("{}/{}", host.to_ascii_lowercase(), path);
    is_valid_repo_slug(&slug).then_some(slug)
}

/// Whether `slug` has the shape Django writes: a lowercase host, then two or more path segments.
pub fn is_valid_repo_slug(slug: &str) -> bool {
    let Some((host, path)) = slug.split_once('/') else {
        return false;
    };
    is_valid_host(host) && path.split('/').count() >= 2 && path.split('/').all(is_valid_segment)
}

fn is_valid_host(host: &str) -> bool {
    let bytes = host.as_bytes();
    !bytes.is_empty()
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'.' || *b == b'-')
        && bytes[0].is_ascii_alphanumeric()
        && bytes[bytes.len() - 1].is_ascii_alphanumeric()
}

fn is_valid_segment(segment: &str) -> bool {
    !segment.is_empty()
        && segment != "."
        && segment != ".."
        && segment
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'~' | b'+' | b'-'))
}

/// A repo path that cannot point outside the repository.
pub fn is_valid_repo_path(path: &str) -> bool {
    !path.is_empty()
        && !path.starts_with('/')
        && path
            .split('/')
            .all(|segment| !segment.is_empty() && segment != "..")
}

pub fn is_full_commit_sha(commit: &str) -> bool {
    commit.len() == 40
        && commit
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(serde::Deserialize)]
    struct SlugCase {
        remote_url: String,
        slug: Option<String>,
    }

    #[test]
    fn parses_the_cases_django_runs() {
        let cases: Vec<SlugCase> =
            serde_json::from_str(include_str!("../../tests/static/repo_slug_cases.json")).unwrap();
        assert!(!cases.is_empty());
        for case in cases {
            assert_eq!(
                parse_repo_slug(&case.remote_url),
                case.slug,
                "{}",
                case.remote_url
            );
        }
    }

    #[test]
    fn accepts_only_the_slug_shape_django_writes() {
        let cases = [
            ("github.com/acme/shop", true),
            ("gitlab.example.com/group/sub/project", true),
            ("GitHub.com/acme/shop", false),
            ("github.com/acme", false),
            ("github.com/acme/../shop", false),
            ("github.com/acme//shop", false),
            ("github.com/acme/shop?x", false),
            ("/acme/shop", false),
        ];
        for (slug, expected) in cases {
            assert_eq!(is_valid_repo_slug(slug), expected, "{slug}");
        }
    }
}
