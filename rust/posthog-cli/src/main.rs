use posthog_cli::cmd;
use tracing::{error, info};

fn main() {
    tracing_subscriber::fmt::init();
    match cmd::Cli::run() {
        Ok(_) => info!("All done, happy hogging!"),
        Err(e) => {
            let msg = match e.exception_id {
                Some(id) => format!("Oops! {} (ID: {})", e.inner, id),
                None => format!("Oops! {:?}", e.inner),
            };
            error!(msg);
        }
    }
}
