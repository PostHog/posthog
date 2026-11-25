//! The emoji a view icon can use: names and tags from emojibase (MIT, see
//! assets/emoji/LICENSE-emojibase), grouped as the picker shows them. The
//! broker checks icons against it, so only emoji the picker offers are kept.
use std::collections::HashMap;

pub struct Entry {
    pub emoji: &'static str,
    pub label: &'static str,
    tags: &'static str,
    pub category: usize,
}
pub struct Category {
    pub key: &'static str,
    pub name: &'static str,
    pub icon: &'static str,
    pub entries: Vec<usize>,
}
pub struct Catalog {
    pub entries: Vec<Entry>,
    pub categories: Vec<Category>,
    by_emoji: HashMap<&'static str, usize>,
}

/// Names and tags from emojibase (MIT, see assets/emoji/LICENSE-emojibase).
pub fn catalog() -> &'static Catalog {
    static CATALOG: std::sync::OnceLock<Catalog> = std::sync::OnceLock::new();
    CATALOG.get_or_init(|| {
        #[derive(serde::Deserialize)]
        struct Raw {
            key: String,
            name: String,
            icon: String,
            items: Vec<(String, String, String)>,
        }
        let raw: Vec<Raw> = serde_json::from_str(include_str!("../assets/emoji.json")).unwrap();
        let leak = |s: String| -> &'static str { Box::leak(s.into_boxed_str()) };
        let mut entries = Vec::new();
        let mut categories = Vec::new();
        for (category, c) in raw.into_iter().enumerate() {
            let mut ids = Vec::new();
            for (emoji, label, tags) in c.items {
                ids.push(entries.len());
                entries.push(Entry {
                    emoji: leak(emoji),
                    label: leak(label),
                    tags: leak(tags),
                    category,
                });
            }
            categories.push(Category {
                key: leak(c.key),
                name: leak(c.name),
                icon: leak(c.icon),
                entries: ids,
            });
        }
        let by_emoji = entries
            .iter()
            .enumerate()
            .map(|(i, e)| (e.emoji, i))
            .collect();
        Catalog {
            entries,
            categories,
            by_emoji,
        }
    })
}

impl Catalog {
    pub fn find(&self, emoji: &str) -> Option<usize> {
        self.by_emoji.get(emoji).copied()
    }
    /// Every term must match the name or a tag; names count for more, and
    /// objects rank above people, which is what views are usually about.
    fn score(&self, entry: &Entry, terms: &[&str]) -> i32 {
        let starts_word = |hay: &str, t: &str| {
            hay.match_indices(t)
                .any(|(at, _)| at == 0 || !hay.as_bytes()[at - 1].is_ascii_alphanumeric())
        };
        let mut score = 0;
        for t in terms {
            score += if entry.label == *t {
                60
            } else if entry.label.starts_with(t) {
                40
            } else if starts_word(entry.label, t) {
                30
            } else if starts_word(entry.tags, t) {
                10
            } else {
                return 0;
            };
        }
        score
            + match self.categories[entry.category].key {
                "objects" => 5,
                "people" => -5,
                _ => 0,
            }
    }
    pub fn search(&self, query: &str) -> Vec<usize> {
        let terms: Vec<String> = query
            .to_lowercase()
            .split_whitespace()
            .map(|t| t.chars().filter(|c| c.is_alphanumeric()).collect())
            .filter(|t: &String| !t.is_empty())
            .collect();
        if terms.is_empty() {
            return vec![];
        }
        let terms: Vec<&str> = terms.iter().map(String::as_str).collect();
        let mut hits: Vec<(i32, usize)> = self
            .entries
            .iter()
            .enumerate()
            .filter_map(|(i, e)| Some((self.score(e, &terms), i)).filter(|(s, _)| *s > 0))
            .collect();
        hits.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
        hits.into_iter().map(|(_, i)| i).collect()
    }
    /// Emoji for a view's name: each word and a few of its synonyms, best
    /// matches first, padded with good all-rounders.
    pub fn suggest(&self, title: &str) -> Vec<usize> {
        const SYNONYMS: &[(&str, &str)] = &[
            ("issue", "bug"),
            ("issues", "bug"),
            ("bugs", "bug"),
            ("notes", "memo pencil"),
            ("note", "memo"),
            ("budget", "money coin"),
            ("finance", "money bank"),
            ("expenses", "money receipt"),
            ("calendar", "calendar"),
            ("schedule", "calendar clock"),
            ("inbox", "inbox envelope"),
            ("email", "envelope"),
            ("deploys", "rocket"),
            ("releases", "rocket package"),
            ("reading", "books"),
            ("habits", "seedling check"),
            ("people", "people"),
            ("team", "people handshake"),
            ("customers", "handshake"),
            ("customer", "handshake"),
            ("interviews", "microphone speech"),
            ("metrics", "chart"),
            ("analytics", "chart"),
            ("dashboard", "chart"),
            ("recipes", "cooking"),
            ("travel", "airplane luggage"),
            ("trips", "airplane"),
            ("roadmap", "map"),
            ("standup", "coffee"),
            ("hiring", "briefcase"),
            ("garden", "seedling"),
            ("ideas", "bulb"),
            ("design", "palette"),
            ("tasks", "check"),
            ("todo", "check"),
            ("projects", "folder"),
            ("support", "headphone"),
            ("music", "musical"),
            ("files", "folder"),
            ("links", "link"),
            ("bookmarks", "bookmark"),
            ("pull", "inbox"),
            ("requests", "inbox"),
            ("prs", "inbox"),
            ("journal", "notebook"),
            ("diary", "notebook"),
            ("reports", "chart clipboard"),
            ("report", "chart clipboard"),
            ("code", "laptop"),
            ("logs", "scroll"),
            ("weather", "sun"),
            ("health", "heart"),
            ("fitness", "running"),
            ("news", "newspaper"),
            ("sales", "money handshake"),
        ];
        let mut out = Vec::new();
        let words: Vec<String> = title
            .to_lowercase()
            .split(|c: char| !c.is_alphanumeric())
            .filter(|w| w.len() > 2)
            .map(str::to_owned)
            .collect();
        for word in &words {
            let extra = SYNONYMS
                .iter()
                .filter(|(w, _)| w == word)
                .flat_map(|(_, s)| s.split(' '));
            // Synonyms first: they say what the word means here ("notes" is a
            // memo, not music); the word itself comes after.
            for term in extra.chain(std::iter::once(word.as_str())) {
                let mut hits: Vec<(i32, usize)> = self
                    .entries
                    .iter()
                    .enumerate()
                    .map(|(i, e)| (self.score(e, &[term]), i))
                    .filter(|(s, _)| *s >= 30)
                    .collect();
                hits.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
                for (_, i) in hits.into_iter().take(6) {
                    if !out.contains(&i) {
                        out.push(i);
                    }
                }
            }
        }
        for emoji in ["📦", "📌", "✨", "🧭", "🗂️", "💡", "🎯", "🔖", "🧩", "🪴"]
        {
            if out.len() >= 16 {
                break;
            }
            if let Some(i) = self.find(emoji)
                && !out.contains(&i)
            {
                out.push(i);
            }
        }
        out.truncate(16);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::catalog;

    #[test]
    fn catalog_loads_and_finds_things_by_name_and_tag() {
        let c = catalog();
        assert!(c.entries.len() > 1000);
        let first = |q: &str| c.entries[c.search(q)[0]].emoji;
        assert_eq!(first("lady beetle"), "🐞");
        assert_eq!(first("rocket"), "🚀");
        // Tags reach things whose name doesn't say it.
        assert!(
            c.search("money")
                .iter()
                .any(|&i| c.entries[i].emoji == "💰")
        );
        assert!(c.search("zzzz nothing").is_empty());
    }

    #[test]
    fn suggestions_follow_the_views_name() {
        let c = catalog();
        let emojis =
            |t: &str| -> Vec<&str> { c.suggest(t).iter().map(|&i| c.entries[i].emoji).collect() };
        assert!(emojis("Issues").contains(&"🐛"));
        assert!(emojis("Reading list").contains(&"📚"));
        // What the word means for a view beats a literal match.
        assert_eq!(emojis("Notes")[0], "📝");
        assert_eq!(emojis("Journal")[0], "📓");
        assert_eq!(emojis("Pull requests")[0], "📥");
        // A name with no match still gets the all-rounders.
        assert_eq!(emojis("Qwxyz").len(), 10);
    }
}
