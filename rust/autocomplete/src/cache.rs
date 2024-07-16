use crate::{config::Config, types::Event};

pub struct PropertyCacheManager {

}

impl PropertyCacheManager {
    pub fn new(_config: &Config) -> Self {
        Self {}
    }

    pub async fn handle_event(&self, _event: Event) {
        
    }
}