use crate::error::WebhookResponseError;
use futures::StreamExt;
use reqwest::Response;

pub async fn first_n_bytes_of_response(
    response: Response,
    n: usize,
) -> Result<String, WebhookResponseError> {
    let mut body = response.bytes_stream();
    let mut buffer = String::with_capacity(n);

    while let Some(chunk) = body.next().await {
        if buffer.len() >= n {
            break;
        }

        let chunk = chunk?;
        let chunk_str = std::str::from_utf8(&chunk)?;
        let upper_bound = std::cmp::min(n - buffer.len(), chunk_str.len());

        if let Some(partial_chunk_str) = chunk_str.get(0..upper_bound) {
            buffer.push_str(partial_chunk_str);
        } else {
            // For whatever reason we are out of bounds. We should never land here
            // given the `std::cmp::min` usage, but I am being extra careful by not
            // using a slice index that would panic instead.
            return Err(WebhookResponseError::ChunkOutOfBoundsError(
                chunk_str.len(),
                upper_bound,
            ));
        }
    }

    Ok(buffer)
}
