# Membership implementation for the four report paths

Status: design only. The public analyzer and four upload forms are live product paths; no self-service membership, account, billing, or paid entitlement is enabled by this file.

| Entitlement | Free preview | Solo | Wind specialist | Team |
| --- | --- | --- | --- | --- |
| Performance report | One-log draft | Monthly quota | Included | Shared quota |
| Incident evidence | One-log draft | Per-case add-on | Per-case add-on | Shared quota with reviewer seats |
| Wind context | Source-labelled reference | Included | Per-point height profiles and source comparison | Included with team policy |
| Team handoff | Inquiry/sample | Inquiry | Inquiry | Organization workspace, roles, review and history |

Do not sell inverse-wind reconstruction or certified findings as current entitlements. Quotas and price points require customer testing and a chosen payment provider.

Implementation order:
1. Add verified user identity, organization membership, and a server-side entitlement table. Keep uploads private to the owning user or organization; establish deletion and retention controls.
2. Add plan products in the payment provider. On checkout, create a pending order tied to a user and plan. Activate or change entitlements only after a signed server-to-server webhook, not after a redirect or client-side flag.
3. Enforce per-plan upload, download, storage and report limits on the server. Make failed payment, cancellation, refunds, duplicate webhooks and quota reset idempotent.
4. Add organization roles for uploader, reviewer and administrator before providing approval states or shared history. Audit each access and approval.
5. Reconcile provider invoices and entitlements daily; expose plan, usage, renewal and cancellation in the account page.

The current `/checkout/<plan>` links can redirect only when valid external payment links are configured. A payment link alone does not identify a site user or grant membership. Until identity and webhooks exist, scope and payment remain a manual pilot workflow.
