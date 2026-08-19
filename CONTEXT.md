# Car Flip Search

The language for identifying BCA auction vehicles whose retail-market pricing suggests a potential resale opportunity. It distinguishes valuation signals from the cost and outcome of a completed flip.

## Auction and valuation

**Auction Lot**:
A vehicle that remains unsold and is offered for sale through BCA, identified by its BCA lot record.
_Avoid_: Auction car, BCA listing

**CAP Clean Price**:
The CAP valuation for a vehicle in clean condition, shown on its BCA Auction Lot record. It is the acquisition-side benchmark for the MVP, not an observed auction purchase price.
_Avoid_: CAP price, clean CAP

**Whole-Pound Amount**:
An exact count of British pounds with no pence. Every price, floor, and spread in this context is a Whole-Pound Amount; other currencies and partial-pound denominations are outside the domain.
_Avoid_: Money, decimal price, currency amount

**Price Spread**:
The signed difference calculated as the lowest Advertised Price among a Candidate Vehicle's Market Comparables minus its CAP Clean Price. It is a valuation signal, not a profit estimate.
_Avoid_: Profit, margin

## Retail-market comparison

**Candidate Vehicle**:
An Auction Lot being assessed against CAP and retail-market pricing for a potential resale opportunity.
_Avoid_: Deal, flip

**Available Candidate**:
A Candidate Vehicle whose BCA Auction Lot remains unsold, has not been withdrawn, and is still within its auction window. Only Available Candidates appear in the Opportunity List.
_Avoid_: Historic candidate, closed lot

**Condition-Eligible Candidate**:
A Candidate Vehicle with known clean condition and no reported write-off or accident damage. Only Condition-Eligible Candidates are included in the MVP.
_Avoid_: Candidate, clean car

**Comparison-Eligible Candidate**:
A Condition-Eligible Candidate with Core Vehicle Identity and mileage sufficiently known to establish Market Comparables.
_Avoid_: Partial match, approximate candidate

**Core Vehicle Identity**:
The attributes that must match between a Candidate Vehicle and a market listing: make, Model Variant, registration year, fuel type, transmission, body style, and door count.
_Avoid_: Broad model family, trim

**Model Variant**:
The model-level engine or badge variant that differentiates vehicles in the same model family, such as A180d and A200d.
_Avoid_: Model family, trim

**Trim Match**:
An optional match of derivative or trim between a Candidate Vehicle and a market listing. It strengthens the comparison but is not required.
_Avoid_: Required identity, eligibility gate

**Market Comparable**:
An Auto Trader Listing that matches a Candidate Vehicle's Core Vehicle Identity and Mileage Band. A Trim Match is preferred but not required.
_Avoid_: Same car, equivalent car

**Mileage Band**:
The permitted mileage difference between a Candidate Vehicle and a Market Comparable, fixed at plus or minus 15,000 miles.
_Avoid_: Similar mileage

**Comparable Supply**:
The count of active Market Comparables for a Candidate Vehicle.
_Avoid_: Quantity, stock level

**Market Scope**:
The geographic coverage of the BCA and Auto Trader comparison market: the United Kingdom.
_Avoid_: Local market, search radius

**High-Mileage Reference**:
An Auto Trader Listing that matches a Candidate Vehicle's Core Vehicle Identity but has mileage above its Mileage Band. It is not a Market Comparable.
_Avoid_: Comparable, match

**Retail Floor**:
A conservative lower-bound retail signal for a low-mileage Candidate Vehicle, derived from the Advertised Prices of its High-Mileage References.
_Avoid_: Predicted sale price, valuation

**Retail-Floor Spread**:
The difference between a Candidate Vehicle's Retail Floor and its CAP Clean Price. It is shown alongside Price Spread whenever a Retail Floor can be established, including where direct Market Comparables also exist; otherwise it is omitted.
_Avoid_: Price Spread, profit

**Auto Trader Listing**:
A vehicle advertisement that is live on Auto Trader at the time of the Market Snapshot.
_Avoid_: Sale, sold car

**Market Snapshot**:
The live UK Auto Trader market observed at a point in time. Historical or inferred sale data is outside the MVP.
_Avoid_: Sales history, sold market

**Seller Type**:
The category of an Auto Trader Listing: private seller or dealer. Both Seller Types are included when selecting Market Comparables and High-Mileage References.
_Avoid_: Retailer type, listing source

**Advertised Price**:
The Cash Price shown on an Auto Trader Listing. It is not evidence of the price at which the vehicle was ultimately sold.
_Avoid_: Sale price, transaction price

**Cash Price**:
The upfront vehicle price advertised on Auto Trader, excluding finance payment illustrations. It is the only listing price used for market evidence.
_Avoid_: Monthly payment, finance price

**Opportunity List**:
The complete set of Comparison-Eligible Candidates and their valuation signals. It has no minimum-spread eligibility threshold; the user filters and sorts it.
_Avoid_: Shortlist, qualified deals

**External Watchlist**:
The watchlist on BCA where the user tracks Auction Lots they may consider. It sits outside Car Flip Search; the dashboard only helps the user reach the relevant Auction Lot.
_Avoid_: App watchlist, local watchlist

**Source Link**:
The captured URL that opens the source page for an Auction Lot or Auto Trader Listing so the user can inspect it. It is optional inspection metadata and does not change domain identity or valuation evidence.
_Avoid_: Derived link, source ID

## Capture

**Capture**:
A saved result set from one run of a BCA or Auto Trader source capture, identified by its unique Capture ID and Search Name. It keeps the original page data, the valid parsed car records, and a skipped-car log.
_Avoid_: Download, export, scrape

**Capture Pair**:
One BCA Capture and one Auto Trader Capture selected together to produce an Opportunity List. The pair is identified by both Capture IDs; their Search Names and saved times provide context but do not define a match.
_Avoid_: Matched search, synchronized capture

**Capture ID**:
The unique identifier of a Capture, never reused or overwritten.
_Avoid_: Folder name, timestamp

**Search Name**:
The user-supplied name of a Capture, recorded in its manifest.
_Avoid_: Search query, filter name

**Skipped-Car Log**:
The part of a Capture that records each car the tool could not validate, identifying the lot where possible and listing every skip reason.
_Avoid_: Error log, discard list
