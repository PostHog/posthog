//! Interactive explorer for the handoff-protocol model.
//!
//! ```sh
//! cargo run -p personhog-stateright -- current
//! cargo run -p personhog-stateright -- current-zombie
//! cargo run -p personhog-stateright -- epoch-fenced
//! ```
//!
//! Serves the Stateright web UI at http://localhost:3000 for stepping
//! through counterexample traces state by state.

use personhog_stateright::model::{HandoffModel, Variant};
use stateright::Model;

fn main() {
    let arg = std::env::args().nth(1).unwrap_or_default();
    let (variant, crashes, zombie_window) = match arg.as_str() {
        "current" => (Variant::Current, 1, 0),
        "current-zombie" => (Variant::Current, 1, 1),
        "epoch-fenced" => (Variant::EpochFenced, 1, 1),
        other => {
            eprintln!(
                "unknown variant {other:?}; expected current | current-zombie | epoch-fenced"
            );
            std::process::exit(2);
        }
    };

    let model = HandoffModel {
        pods: 2,
        routers: 2,
        partitions: 1,
        variant,
        writes: 2,
        reads: 1,
        crashes,
        rejoins: 0,
        zombie_window,
    };
    println!("exploring {arg} at http://localhost:3000 …");
    model.checker().serve("localhost:3000");
}
