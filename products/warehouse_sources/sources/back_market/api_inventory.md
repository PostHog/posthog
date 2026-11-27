# Back Market endpoint inventory

This inventory covers the four added tables and their dependency on `listings`.
Endpoint contracts come from the [official OpenAPI specification](https://api.backmarket.dev/bundled_openapi.yaml), checked on November 27, 2026.
The source uses `https://www.backmarket.com` with the paths below.

## Authentication and access

All four endpoints declare `ApiKeyAuth` or `BasicAuth` in the specification.
The source uses the seller token from the Back Office Integrations page as `Authorization: Basic <token>`.
The specification declares no OAuth scopes for these endpoints.
Returns require a BackShip subscription. BuyBack orders require an authenticated merchant.

## Endpoint contracts

Primary keys below use API field names, before warehouse column normalization.

| Table                 | GET path                                 | Row grain                                                 | Pagination and response                        | Primary key                            | Incremental candidate                                             |
| --------------------- | ---------------------------------------- | --------------------------------------------------------- | ---------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------- |
| `backbox_competitors` | `/ws/backbox/v1/competitors/{listingId}` | One competitor listing and market for each parent listing | One bare array per parent; no child pagination | `_listings_id`, `listing_id`, `market` | None documented; full refresh                                     |
| `care_folders`        | `/ws/sav`                                | One seller after-sales case                               | `page`, 10 rows per page; `results` and `next` | `id`                                   | `date_modification` through `last_modification_date`              |
| `returns`             | `/ws/shipping/v1/returns`                | One return shipment                                       | `page`; `results` and `next`                   | `shipmentId`                           | `dateCreation` through `start_date`                               |
| `buyback_orders`      | `/ws/buyback/v1/orders`                  | One BuyBack order                                         | `page`; `results` and `next`                   | `orderPublicId`                        | `modificationDate` through the query parameter with the same name |

The source starts list pagination at page 1 and increments while `next` is truthy.
It saves the next page for resume. It does not request a custom page size.

## Competitor dependency

The source reads parent listings from `/ws/listings`, with `results`, `next`, and page-number pagination.
It uses the parent's `id` UUID as `listingId`, not the parent's numeric `listing_id`.
It copies that UUID into `_listings_id` on each competitor row.
The composite key separates markets and keeps results from different parent requests distinct.
The source ignores child 404 responses and saves progress after each completed parent.
Resume state includes parent pagination and child progress.

## Incremental limits

- Care Folders accept `last_modification_date` in `YYYY-MM-DD-hh-mm` format.
  The specification says the filter returns more recent cases, so the lower bound is exclusive.
  The source subtracts one minute before formatting the watermark to retain cases at exact minute boundaries.
  Repeated rows require deduplication by the primary key when storing incremental results.
- Returns accept `start_date` as an inclusive creation timestamp.
  This filter cannot capture later changes to older returns. Use full refresh to retrieve those changes.
- BuyBack orders accept `modificationDate` as a date.
  The source rereads the watermark day to retain updates within that day.
  Repeated rows require deduplication by the primary key when storing incremental results.
- Competitor responses expose no documented timestamp filter. Each full refresh reads the current competitor snapshot.

The source does not declare a guaranteed row order for these endpoints.
