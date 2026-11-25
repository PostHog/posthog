use gpui::Window;

/// Semantic content type for an [`Input`](super::Input).
///
/// These variants mirror Swift's text content types.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputContentType {
    /// A person's full name.
    Name,
    /// A name prefix, such as Mr. or Dr.
    NamePrefix,
    /// A person's given name.
    GivenName,
    /// A person's middle name.
    MiddleName,
    /// A person's family name.
    FamilyName,
    /// A name suffix, such as Jr. or PhD.
    NameSuffix,
    /// A nickname.
    Nickname,
    /// A job title.
    JobTitle,
    /// An organization or company name.
    OrganizationName,
    /// A location name.
    Location,
    /// A full street address.
    FullStreetAddress,
    /// The first line of a street address.
    StreetAddressLine1,
    /// The second line of a street address.
    StreetAddressLine2,
    /// A city or locality.
    AddressCity,
    /// A state, province, or region.
    AddressState,
    /// A combined city and state.
    AddressCityAndState,
    /// A sublocality, district, or neighborhood.
    Sublocality,
    /// A country name.
    CountryName,
    /// A postal or ZIP code.
    PostalCode,
    /// A telephone number.
    TelephoneNumber,
    /// An email address.
    EmailAddress,
    /// A URL.
    Url,
    /// A credit card number.
    CreditCardNumber,
    /// The full name on a credit card.
    CreditCardName,
    /// The given name on a credit card.
    CreditCardGivenName,
    /// The middle name on a credit card.
    CreditCardMiddleName,
    /// The family name on a credit card.
    CreditCardFamilyName,
    /// The security code on a credit card.
    CreditCardSecurityCode,
    /// A credit card expiration date.
    CreditCardExpiration,
    /// A credit card expiration month.
    CreditCardExpirationMonth,
    /// A credit card expiration year.
    CreditCardExpirationYear,
    /// A credit card type.
    CreditCardType,
    /// A username or account identifier.
    Username,
    /// The password for the account identified by the username field.
    Password,
    /// A new password, such as during sign up or password reset.
    NewPassword,
    /// A one-time verification code.
    OneTimeCode,
    /// A parcel shipment tracking number.
    ShipmentTrackingNumber,
    /// An airline flight number.
    FlightNumber,
    /// A date, time, or duration.
    DateTime,
    /// A birthdate.
    Birthdate,
    /// A birthdate day.
    BirthdateDay,
    /// A birthdate month.
    BirthdateMonth,
    /// A birthdate year.
    BirthdateYear,
    /// An eSIM EID.
    CellularEid,
    /// A cellular IMEI.
    CellularImei,
}

impl InputContentType {
    #[cfg(target_os = "macos")]
    pub(crate) const fn ns_text_content_type(self) -> Option<&'static str> {
        match self {
            Self::Name => Some("name"),
            Self::NamePrefix => Some("honorific-prefix"),
            Self::GivenName => Some("given-name"),
            Self::MiddleName => Some("additional-name"),
            Self::FamilyName => Some("family-name"),
            Self::NameSuffix => Some("honorific-suffix"),
            Self::Nickname => Some("nickname"),
            Self::JobTitle => Some("organization-title"),
            Self::OrganizationName => Some("organization"),
            Self::Location => Some("location"),
            Self::FullStreetAddress => Some("street-address"),
            Self::StreetAddressLine1 => Some("address-line1"),
            Self::StreetAddressLine2 => Some("address-line2"),
            Self::AddressCity => Some("address-level2"),
            Self::AddressState => Some("address-level1"),
            Self::AddressCityAndState => Some("address-level1+2"),
            Self::Sublocality => Some("address-level3"),
            Self::CountryName => Some("country-name"),
            Self::PostalCode => Some("postal-code"),
            Self::TelephoneNumber => Some("tel"),
            Self::EmailAddress => Some("email"),
            Self::Url => Some("url"),
            Self::CreditCardNumber => Some("cc-number"),
            Self::CreditCardName => Some("cc-name"),
            Self::CreditCardGivenName => Some("cc-given-name"),
            Self::CreditCardMiddleName => Some("cc-additional-name"),
            Self::CreditCardFamilyName => Some("cc-family-name"),
            Self::CreditCardSecurityCode => Some("cc-csc"),
            Self::CreditCardExpiration => Some("cc-exp"),
            Self::CreditCardExpirationMonth => Some("cc-exp-month"),
            Self::CreditCardExpirationYear => Some("cc-exp-year"),
            Self::CreditCardType => Some("cc-type"),
            Self::Username => Some("username"),
            Self::Password => Some("password"),
            Self::NewPassword => Some("new-password"),
            Self::OneTimeCode => Some("one-time-code"),
            Self::ShipmentTrackingNumber => Some("shipment-tracking-number"),
            Self::FlightNumber => Some("flight-number"),
            Self::DateTime => Some("date-time"),
            Self::Birthdate => Some("bday"),
            Self::BirthdateDay => Some("bday-day"),
            Self::BirthdateMonth => Some("bday-month"),
            Self::BirthdateYear => Some("bday-year"),
            Self::CellularEid | Self::CellularImei => None,
        }
    }
}

/// Tells the OS what the focused input is used for, to let the autofill offer
/// the matched value.
///
/// The `editable` is false when the input is `disabled` or `readonly`, in that
/// case the autofill has nothing to fill in, so the content type is not synced.
pub(super) fn sync_native_content_type(
    window: &mut Window,
    content_type: Option<InputContentType>,
    editable: bool,
) {
    if !editable {
        return;
    }

    #[cfg(all(target_os = "macos", not(test)))]
    gpui_base::input::set_text_content_type(
        window,
        content_type.and_then(InputContentType::ns_text_content_type),
    );

    #[cfg(any(not(target_os = "macos"), test))]
    let _ = (window, content_type);
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;

    #[test]
    fn content_type_maps_to_ns_text_content_type_values() {
        let content_types = [
            (InputContentType::Name, Some("name")),
            (InputContentType::NamePrefix, Some("honorific-prefix")),
            (InputContentType::GivenName, Some("given-name")),
            (InputContentType::MiddleName, Some("additional-name")),
            (InputContentType::FamilyName, Some("family-name")),
            (InputContentType::NameSuffix, Some("honorific-suffix")),
            (InputContentType::Nickname, Some("nickname")),
            (InputContentType::JobTitle, Some("organization-title")),
            (InputContentType::OrganizationName, Some("organization")),
            (InputContentType::Location, Some("location")),
            (InputContentType::FullStreetAddress, Some("street-address")),
            (InputContentType::StreetAddressLine1, Some("address-line1")),
            (InputContentType::StreetAddressLine2, Some("address-line2")),
            (InputContentType::AddressCity, Some("address-level2")),
            (InputContentType::AddressState, Some("address-level1")),
            (
                InputContentType::AddressCityAndState,
                Some("address-level1+2"),
            ),
            (InputContentType::Sublocality, Some("address-level3")),
            (InputContentType::CountryName, Some("country-name")),
            (InputContentType::PostalCode, Some("postal-code")),
            (InputContentType::TelephoneNumber, Some("tel")),
            (InputContentType::EmailAddress, Some("email")),
            (InputContentType::Url, Some("url")),
            (InputContentType::CreditCardNumber, Some("cc-number")),
            (InputContentType::CreditCardName, Some("cc-name")),
            (InputContentType::CreditCardGivenName, Some("cc-given-name")),
            (
                InputContentType::CreditCardMiddleName,
                Some("cc-additional-name"),
            ),
            (
                InputContentType::CreditCardFamilyName,
                Some("cc-family-name"),
            ),
            (InputContentType::CreditCardSecurityCode, Some("cc-csc")),
            (InputContentType::CreditCardExpiration, Some("cc-exp")),
            (
                InputContentType::CreditCardExpirationMonth,
                Some("cc-exp-month"),
            ),
            (
                InputContentType::CreditCardExpirationYear,
                Some("cc-exp-year"),
            ),
            (InputContentType::CreditCardType, Some("cc-type")),
            (InputContentType::Username, Some("username")),
            (InputContentType::Password, Some("password")),
            (InputContentType::NewPassword, Some("new-password")),
            (InputContentType::OneTimeCode, Some("one-time-code")),
            (
                InputContentType::ShipmentTrackingNumber,
                Some("shipment-tracking-number"),
            ),
            (InputContentType::FlightNumber, Some("flight-number")),
            (InputContentType::DateTime, Some("date-time")),
            (InputContentType::Birthdate, Some("bday")),
            (InputContentType::BirthdateDay, Some("bday-day")),
            (InputContentType::BirthdateMonth, Some("bday-month")),
            (InputContentType::BirthdateYear, Some("bday-year")),
            (InputContentType::CellularEid, None),
            (InputContentType::CellularImei, None),
        ];

        for (content_type, native_value) in content_types {
            assert_eq!(content_type.ns_text_content_type(), native_value);
        }
    }
}
