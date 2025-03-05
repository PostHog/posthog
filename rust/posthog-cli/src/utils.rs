use anyhow::{Context, Error};

// IF `POSTHOG_HOME` is set, use that, otherwise use $HOME/.posthog
pub fn posthog_home_dir() -> String {
    match std::env::var("POSTHOG_HOME") {
        Ok(home) => home,
        Err(_) => {
            let home = std::env::var("HOME").expect("Could not determine home directory");
            format!("{}/.posthog", home)
        }
    }
}

pub fn ensure_homdir_exists() -> Result<(), Error> {
    let home = posthog_home_dir();
    std::fs::create_dir_all(home.clone())
        .context(format!("While trying to create directory {}", home))?;
    Ok(())
}
