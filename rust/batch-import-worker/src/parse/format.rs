use std::sync::Arc;

use anyhow::Error;
use common_types::InternallyCapturedEvent;
use serde::{de::DeserializeOwned, Deserialize, Serialize};

use crate::{context::AppContext, job::model::JobModel};

use super::{
    content::{mixpanel::MixpanelEvent, ContentType, TransformContext},
    Parsed,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum FormatConfig {
    JsonLines {
        skip_blanks: bool,
        content: ContentType,
    },
}

impl FormatConfig {
    pub async fn get_parser(
        &self,
        model: &JobModel,
        context: Arc<AppContext>,
    ) -> Result<impl Fn(Vec<u8>) -> Result<Parsed<Vec<InternallyCapturedEvent>>, Error>, Error>
    {
        // Only support json-lines for now
        let Self::JsonLines {
            skip_blanks,
            content,
        } = self;

        let format_parse = json_nd(*skip_blanks);

        let transform_context = TransformContext {
            team_id: model.team_id,
            token: context.get_token_for_team_id(model.team_id).await?,
        };

        let parser = match content {
            ContentType::Mixpanel => {
                let event_transform = MixpanelEvent::parse_fn(transform_context);
                move |data| {
                    let parsed: Parsed<Vec<MixpanelEvent>> = format_parse(data)?;
                    let consumed = parsed.consumed;
                    let result: Result<_, Error> =
                        parsed.data.into_iter().map(&event_transform).collect();
                    Ok(Parsed {
                        data: result?,
                        consumed,
                    })
                }
            }
        };

        Ok(parser)
    }
}

pub const fn newline_delim<T>(
    skip_blank_lines: bool,
    inner: impl Fn(&str) -> Result<T, Error>,
) -> impl Fn(Vec<u8>) -> Result<Parsed<Vec<T>>, Error> {
    let out = move |data: Vec<u8>| {
        // zero-copy conversion, important because our consumed tracking below is in bytes,
        // and we have to know how many bytes /of the input/ we've read, which means we have to operate
        // on the input without any representation conversions
        let data = std::str::from_utf8(data.as_slice())?;
        let line_count = data.lines().count();

        let lines = data.lines();
        let all_but_last = lines.clone().take(line_count - 1);
        let last = lines.last();

        let mut results = Vec::with_capacity(line_count);
        for line in all_but_last {
            if line.len() == 0 && skip_blank_lines {
                continue;
            }
            let parsed = (inner)(line)?;
            results.push(parsed);
        }

        let mut bytes_read = data.as_bytes().len();

        if let Some(last) = last {
            // NOTE - we exclude the "skip_blank_lines" check here, because
            // we can't actually know if the 0 bytes following the \n is a
            // blank line, or just a chunk boundary. The following chunk, if it
            // is a chunk boundary, will either start with a newline character,
            // indicating this /was/ a blank line, or it won't, indicating it wasn't.
            if last.len() > 0 {
                match inner(last) {
                    Ok(parsed) => {
                        results.push(parsed);
                    }
                    Err(_) => {
                        // if we can't parse the last line, we don't want to consume it
                        // so we subtract its length from the total bytes read
                        bytes_read -= last.len();
                    }
                }
            }
        }

        return Ok(Parsed {
            data: results,
            consumed: bytes_read,
        });
    };

    out
}

pub const fn json_nd<T>(skip_blank_lines: bool) -> impl Fn(Vec<u8>) -> Result<Parsed<Vec<T>>, Error>
where
    T: DeserializeOwned,
{
    newline_delim(skip_blank_lines, |line| {
        let parsed = serde_json::from_str(line)?;
        Ok(parsed)
    })
}

#[cfg(test)]
mod tests {
    use crate::source::{folder::FolderSource, DataSource};

    use super::*;
    use serde::Deserialize;
    use std::fs;
    use tempfile::TempDir;

    #[derive(Deserialize, Debug, PartialEq)]
    struct TestData {
        id: i32,
        name: String,
    }

    async fn setup_test_files() -> (TempDir, FolderSource) {
        let temp_dir = TempDir::new().unwrap();
        fs::write(
            temp_dir.path().join("data.jsonl"),
            r#"{"id": 1, "name": "test1"}
{"id": 2, "name": "test2"}
{"id": 3, "name": "test3"}"#,
        )
        .unwrap();

        fs::write(
            temp_dir.path().join("blank_lines.jsonl"),
            r#"{"id": 1, "name": "test1"}

{"id": 2, "name": "test2"}
"#,
        )
        .unwrap();

        let source = FolderSource::new(temp_dir.path().to_str().unwrap().to_string())
            .await
            .unwrap();

        (temp_dir, source)
    }

    #[tokio::test]
    async fn test_json_nd_parsing() {
        let (_temp_dir, source) = setup_test_files().await;
        let chunk = source.get_chunk("data.jsonl", 0, 100).await.unwrap();
        let chunk_len = chunk.len();
        let parsed = json_nd::<TestData>(false)(chunk).unwrap();

        assert_eq!(parsed.data.len(), 3);
        assert_eq!(
            parsed.data[0],
            TestData {
                id: 1,
                name: "test1".to_string()
            }
        );
        assert_eq!(parsed.consumed, chunk_len);
    }

    #[tokio::test]
    async fn test_json_nd_with_blank_lines() {
        let (_temp_dir, source) = setup_test_files().await;
        let data = source.get_chunk("blank_lines.jsonl", 0, 100).await.unwrap();

        let parsed_with_blanks = json_nd::<TestData>(true)(data.clone()).unwrap();
        assert_eq!(parsed_with_blanks.data.len(), 2);

        // IF we're not skipping blank lines, an empty line will cause json parsing
        // to fail, and we should get an error
        let should_be_error = json_nd::<TestData>(false)(data);
        assert!(should_be_error.is_err());
    }

    #[tokio::test]
    async fn test_partial_line() {
        let (_temp_dir, source) = setup_test_files().await;
        let data = source.get_chunk("data.jsonl", 0, 30).await.unwrap();
        let parsed = json_nd::<TestData>(false)(data).unwrap();

        assert_eq!(parsed.data.len(), 1);
        // 26 "data" characters, plus the newline
        assert_eq!(parsed.consumed, 27);
    }
}
