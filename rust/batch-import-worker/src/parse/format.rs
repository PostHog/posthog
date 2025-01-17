use std::sync::Arc;

use anyhow::Error;
use common_types::{InternallyCapturedEvent, RawEvent};
use serde::{de::DeserializeOwned, Deserialize, Serialize};

use crate::{context::AppContext, job::model::JobModel};

use super::{
    content::{
        captured::captured_parse_fn, mixpanel::MixpanelEvent, ContentType, TransformContext,
    },
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

pub type ParserFn = Box<dyn Fn(Vec<u8>) -> Result<Parsed<Vec<InternallyCapturedEvent>>, Error>>;

impl FormatConfig {
    pub async fn get_parser(
        &self,
        model: &JobModel,
        context: Arc<AppContext>,
    ) -> Result<ParserFn, Error> {
        // Only support json-lines for now
        let Self::JsonLines {
            skip_blanks,
            content,
        } = self;

        let transform_context = TransformContext {
            team_id: model.team_id,
            token: context.get_token_for_team_id(model.team_id).await?,
        };

        match content {
            ContentType::Mixpanel => {
                let format_parse = json_nd(*skip_blanks);
                let event_transform = MixpanelEvent::parse_fn(transform_context);
                let parser = move |data| {
                    let parsed: Parsed<Vec<MixpanelEvent>> = format_parse(data)?;
                    let consumed = parsed.consumed;
                    let result: Result<_, Error> =
                        parsed.data.into_iter().map(&event_transform).collect();
                    Ok(Parsed {
                        data: result?,
                        consumed,
                    })
                };

                Ok(Box::new(parser))
            }
            ContentType::Captured => {
                let format_parse = json_nd(*skip_blanks);
                let event_transform = captured_parse_fn(transform_context);
                let parser = move |data| {
                    let parsed: Parsed<Vec<RawEvent>> = format_parse(data)?;
                    let consumed = parsed.consumed;
                    let result: Result<_, Error> =
                        parsed.data.into_iter().map(&event_transform).collect();
                    Ok(Parsed {
                        data: result?,
                        consumed,
                    })
                };

                Ok(Box::new(parser))
            }
        }
    }
}

const NEWLINE_DELIM: u8 = b'\n';

pub const fn newline_delim<T>(
    skip_blank_lines: bool,
    inner: impl Fn(&str) -> Result<T, Error>,
) -> impl Fn(Vec<u8>) -> Result<Parsed<Vec<T>>, Error> {
    let out = move |data: Vec<u8>| {
        let mut out = Vec::new();

        let mut cursor = 0;
        let mut last_consumed_byte = 0;

        // TODO - I'm reasonably sure this is actually invalid in the face of utf-8 encoding... we should immediately parse the
        // data as utf-8, and then consume character-by-character, marking how many bytes we consume as we go. I could redesign
        // this to do that.
        while cursor < data.len() {
            // The cursor != 0 bit here is because the "this might be the end of the file" handling below this can sometimes
            // cause the next chunk to start exactly on a newline. This does run the risk of accidentally skipping a blank line,
            // but we generally don't consider newlines important anyway (skip_blank_lines is generally only set to false to ensure
            // the presence of one in the input will cause the inner function to return an error, not because they're semantically
            // relevant)
            if data[cursor] == NEWLINE_DELIM && cursor != 0 {
                let line = std::str::from_utf8(&data[last_consumed_byte..cursor])?;
                if !skip_blank_lines || !line.trim().is_empty() {
                    out.push(inner(line.trim())?);
                }
                last_consumed_byte = cursor;
            }

            // If we're at the end of the chunk, and we didn't just consume a line, we should try to parse the last line,
            // under the assumption its the final line of the overall file
            if cursor == data.len() - 1 && last_consumed_byte < cursor {
                let line = std::str::from_utf8(&data[last_consumed_byte..cursor + 1])?;
                if !skip_blank_lines || !line.trim().is_empty() {
                    let Ok(t) = inner(line.trim()) else {
                        // A failure here generally indicates we're just at the end of the chunk, rather than the end of the file,
                        // so we should just return the parsed data we have so far
                        break;
                    };
                    out.push(t);
                }
                last_consumed_byte = cursor;
            }

            cursor += 1;
        }

        let parsed = Parsed {
            data: out,
            consumed: last_consumed_byte + 1,
        };

        Ok(parsed)
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
