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

use clap::{Parser, ValueEnum};

use personhog_stateright::model::{HandoffModel, Variant};
use stateright::Model;

#[derive(Parser)]
struct Args {
    #[arg(value_enum)]
    scenario: Scenario,
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum Scenario {
    /// Failures without zombie windows.
    Current,
    /// The double-zombie residual, with counterexamples.
    CurrentZombie,
    /// The epoch-fencing fix.
    EpochFenced,
}

fn main() {
    let args = Args::parse();
    let (variant, crashes, zombie_window) = match args.scenario {
        Scenario::Current => (Variant::Current, 1, 0),
        Scenario::CurrentZombie => (Variant::Current, 1, 1),
        Scenario::EpochFenced => (Variant::EpochFenced, 1, 1),
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
    println!("exploring {:?} at http://localhost:3000 …", args.scenario);
    model.checker().serve("localhost:3000");
}
