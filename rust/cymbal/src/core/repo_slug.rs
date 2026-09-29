//! Repo slugs name the stored file list of a repository, for example `github.com/acme/shop`.
//! Django writes the list under the slug, and cymbal reads it back under the same slug.

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

pub fn is_full_commit_sha(commit: &str) -> bool {
    commit.len() == 40
        && commit
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
mod tests {
    use super::*;

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
