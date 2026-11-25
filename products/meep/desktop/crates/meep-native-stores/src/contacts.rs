//! Read names and contact details from Contacts. The host supplies the search predicate.
use crate::{Access, Privacy};
use anyhow::Result;

/// One person or company, untrimmed: the host controls which fields it returns.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Contact {
    pub id: String,
    pub name: Option<String>,
    pub organization: Option<String>,
    pub job_title: Option<String>,
    /// `(label, value)`, labels already in the person's words ("home", "work").
    pub emails: Vec<(Option<String>, String)>,
    pub phones: Vec<(Option<String>, String)>,
}

/// Call these blocking methods off the UI thread.
pub trait Store: Privacy {
    /// The contacts `keep` accepts, at most `max`, in the address book's order.
    fn find(&self, keep: &(dyn Fn(&Contact) -> bool + Sync), max: usize) -> Result<Vec<Contact>>;
    fn get(&self, id: &str) -> Result<Option<Contact>>;
}

pub struct ContactStore;

#[cfg(target_os = "macos")]
mod macos {
    use super::*;
    use crate::{bundled, decision, text};
    use objc2::{AnyThread, Message, rc::Retained, runtime::ProtocolObject};
    use objc2_contacts::*;
    use objc2_foundation::{NSArray, NSString};
    use std::cell::RefCell;

    fn keys() -> Retained<NSArray<ProtocolObject<dyn CNKeyDescriptor>>> {
        unsafe {
            let mut keys: Vec<Retained<ProtocolObject<dyn CNKeyDescriptor>>> = [
                CNContactIdentifierKey,
                CNContactOrganizationNameKey,
                CNContactJobTitleKey,
                CNContactEmailAddressesKey,
                CNContactPhoneNumbersKey,
            ]
            .into_iter()
            .map(|key| ProtocolObject::from_retained(key.retain()))
            .collect();
            keys.push(CNContactFormatter::descriptorForRequiredKeysForStyle(
                CNContactFormatterStyle::FullName,
            ));
            NSArray::from_retained_slice(&keys)
        }
    }
    fn label(label: Option<Retained<NSString>>) -> Option<String> {
        text(label.map(|l| unsafe { CNLabeledValue::<NSString>::localizedStringForLabel(&l) }))
    }
    fn contact(c: &CNContact) -> Contact {
        unsafe {
            Contact {
                id: c.identifier().to_string(),
                name: text(CNContactFormatter::stringFromContact_style(
                    c,
                    CNContactFormatterStyle::FullName,
                )),
                organization: text(Some(c.organizationName())),
                job_title: text(Some(c.jobTitle())),
                emails: c
                    .emailAddresses()
                    .iter()
                    .filter_map(|e| Some((label(e.label()), text(Some(e.value()))?)))
                    .collect(),
                phones: c
                    .phoneNumbers()
                    .iter()
                    .filter_map(|p| Some((label(p.label()), text(Some(p.value().stringValue()))?)))
                    .collect(),
            }
        }
    }

    impl Privacy for ContactStore {
        fn access(&self) -> Result<Access> {
            bundled("Contacts")?;
            Ok(
                match unsafe {
                    CNContactStore::authorizationStatusForEntityType(CNEntityType::Contacts)
                } {
                    CNAuthorizationStatus::Authorized => Access::Full,
                    CNAuthorizationStatus::Limited => Access::Limited,
                    CNAuthorizationStatus::Denied => Access::Denied,
                    CNAuthorizationStatus::Restricted => Access::Restricted,
                    _ => Access::NotDetermined,
                },
            )
        }
        fn request(&self) -> Result<bool> {
            bundled("Contacts")?;
            let store = unsafe { CNContactStore::new() };
            // Contacts copies the block; `store` stays alive until the decision.
            let granted = decision("Contacts", |callback| unsafe {
                store.requestAccessForEntityType_completionHandler(CNEntityType::Contacts, callback)
            });
            drop(store);
            granted
        }
    }
    impl Store for ContactStore {
        fn find(
            &self,
            keep: &(dyn Fn(&Contact) -> bool + Sync),
            max: usize,
        ) -> Result<Vec<Contact>> {
            if max == 0 {
                return Ok(Vec::new());
            }
            crate::require_read(self, "Contacts")?;
            objc2::rc::autoreleasepool(|_| unsafe {
                let store = CNContactStore::new();
                let request = CNContactFetchRequest::initWithKeysToFetch(
                    CNContactFetchRequest::alloc(),
                    &keys(),
                );
                request.setUnifyResults(true);
                let found = RefCell::new(vec![]);
                // Synchronous enumeration on the calling worker thread.
                let block = block2::StackBlock::new(
                    |c: std::ptr::NonNull<CNContact>,
                     stop: std::ptr::NonNull<objc2::runtime::Bool>| {
                        let c = contact(c.as_ref());
                        let mut found = found.borrow_mut();
                        if keep(&c) {
                            found.push(c);
                        }
                        if found.len() >= max {
                            *stop.as_ptr() = objc2::runtime::Bool::YES;
                        }
                    },
                );
                let mut error = None;
                if !store.enumerateContactsWithFetchRequest_error_usingBlock(
                    &request,
                    Some(&mut error),
                    &block,
                ) {
                    anyhow::bail!(
                        "Contacts could not be read: {}",
                        error
                            .map(|e| e.localizedDescription().to_string())
                            .unwrap_or_default()
                    );
                }
                Ok(found.into_inner())
            })
        }
        fn get(&self, id: &str) -> Result<Option<Contact>> {
            crate::require_read(self, "Contacts")?;
            objc2::rc::autoreleasepool(|_| unsafe {
                let store = CNContactStore::new();
                match store.unifiedContactWithIdentifier_keysToFetch_error(
                    &NSString::from_str(id),
                    &keys(),
                ) {
                    Ok(c) => Ok(Some(contact(&c))),
                    Err(e) if e.code() == CNErrorCode::RecordDoesNotExist.0 => Ok(None),
                    Err(e) => {
                        anyhow::bail!("Contacts could not be read: {}", e.localizedDescription())
                    }
                }
            })
        }
    }
}

#[cfg(not(target_os = "macos"))]
impl Privacy for ContactStore {
    fn access(&self) -> Result<Access> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
    fn request(&self) -> Result<bool> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
}

#[cfg(not(target_os = "macos"))]
impl Store for ContactStore {
    fn find(&self, _: &(dyn Fn(&Contact) -> bool + Sync), _: usize) -> Result<Vec<Contact>> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
    fn get(&self, _: &str) -> Result<Option<Contact>> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
}
