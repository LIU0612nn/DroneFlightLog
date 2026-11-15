# Report formats: observed sources and product decisions

Checked 2026-11-12. Public service pages describe workflows, not necessarily downloadable customer reports. Do not present an inferred layout as a company's actual template.

| Source | Publicly observable format or workflow | What Drone Flight Report borrows |
| --- | --- | --- |
| [NextLeap A10 maintenance manual, Tables 6 and 9](https://nextleap-aeronautics.com/wp-content/uploads/2026/01/MaintenanceManual-8.pdf#page=83) | Actual field-service and company-service forms. Case/aircraft identity, issue, inspection, affected/replaced components, root cause, warranty, return-to-service decision and engineer signatures. | Incident PDF includes an original repair-intake handoff page. Technician-only fields remain blank. No copied OEM layout or certification wording. |
| [D1 Store Enterprise RMA](https://forms.d1store.app/rma/enterprise) | Actual intake form: customer, product, serial, service type, symptom categories, additional details and consent for service-related log processing. | Incident upload asks for organization, work-order reference, aircraft, symptom and time hint. It is not a repair order or consent for secondary data sales. |
| [Jamison Tech](https://jamisontech.com/services/drone-services/) | Public service description: damage quote, log/telemetry/battery-based diagnostic and written claim support. No public report template. | Provide a compact source-linked log-evidence appendix that a human diagnostician may use in a claim workflow. Do not label it a claim decision. |
| [Backcountry Drones](https://backcountrydrones.com/services/drone-repair) | Public workflow: analyze logs before opening aircraft; crash analysis can be sold without repair; write a second-by-second timeline and state competing interpretations. No public PDF template. | Incident page gives a chronological evidence worksheet and explicit unresolved questions. |
| [Meis Systems](https://meissystems.ca/) | Public workflow: model/issue/photos intake, inspection and quote before repair. No public report template or verified BIN/ULG support claim on the current page. | Keep the repair decision and quote/authorization fields separate from automated log findings. |
| [Odakon diagnostic guide](https://odakon.com/en/technical-support/dji-drone-diagnostic-report-before-after-repair/) | Describes pre/post electronic module diagnostics and comparisons. Coverage depends on model; it does not prove physical condition. | Keep post-repair checks as technician work, rather than presenting a pre-repair log PDF as a completed repair report. |
| [AYNA public log-analysis sample](https://ayna.com/log-analyzer/) | Browser sample groups findings by system, severity, values, event time and recommended action. This is an analysis view, not a repair certificate. | Put the important observed event and action question before long charts. |

## Current report paths

1. **Performance:** single-flight record, telemetry coverage, trajectory and charts; human verifies client handoff.
2. **Incident:** reported symptom, timestamped log evidence, gaps, repair-intake handoff with blank physical-inspection/repair/release fields.
3. **Wind:** regional/model reference and logged wind separated by source; available height profile; future time/position/height matching and telemetry-based estimation are labeled as future or research.
4. **Team:** project/aircraft/pilot labels and a review checklist; it does not imply a live approval or account workflow.

## Where one-click generation can help

- Pre-fill a repeatable evidence appendix, event sequence, data coverage and source labels from a log.
- Let a shop attach it to a case before inspection and avoid retyping charts and event times.
- Preserve uncertainty: a log event is not a physical fault diagnosis, and model wind is not local measured wind.

This is a product opportunity inferred from the public workflows above, not evidence that these companies have agreed to use the tool or that their own report creation is slow. Physical inspection, quotation, warranty decision, repair, post-repair testing and release remain human/organization-controlled steps.

## Industry handoff benchmark (checked 2026-11-15)

The optional industry page on each report path borrows **field order and evidence boundaries**, not another company's graphic layout or wording. It is a flight-evidence attachment, not a completed service certificate.

| Workflow and public source | Observed public evidence | Adopted handoff fields | Still missing from a flight log |
| --- | --- | --- | --- |
| [Eye In The Sky](https://eyeintheskyhub.com/contact), [412 Aerials](https://www.412aerials.com/petsearch) | Lost-dog intake asks last location and circumstances. The search provider checks airspace, weather and topography and plans a search area. A downloadable client report format was not verified. | Case/area, last known location, dated flight evidence, search-result review slot. | Thermal or visual sightings, verified search coverage, ground-team decisions. |
| [Skywalker Agro](https://www.skywalkeragro.com/en/services/) | Public operational report shows work order, client/property, fields, treated area, weather windows, flight parameters, agronomic prescription, maps, pilot and field notes. | Field/work-order, crop/treatment reference, dated flight evidence, weather-source boundary. | Verified treated area, product/dose/flow/nozzle, on-site weather, licensed sign-off. |
| [Drone Force](https://www.droneforcellc.com/deliverables) | Customer report and portal organize asset, position, severity, annotated image and recommended action; report and KMZ are delivered after field work. | Site/work-order, asset ID, dated flight evidence, review slots for defect and action. | Defect identification, severity, annotated imagery, inspector approval. |

The new optional handoff page never infers the right-column outcomes. The operator supplies a site and subject label; all other field results remain explicitly pending. This should be tested with a real authorized service partner before becoming a paid report type.

## Interview-to-roadmap mapping

| Question to validate with operators | Potential repeatable step | Product track |
| --- | --- | --- |
| How many logs are matched to jobs and checked manually? | Parse, identify source, join a flight to a work-order ID, expose missing fields. | D (data), P (report UX), S (team workflow) |
| What do customers receive, and which fields are retyped? | Export an evidence appendix in the customer's chosen PDF/CSV/KMZ format. | P and S |
| Where does the current software leave a gap? | Only build a narrow automation after a concrete example and permission to inspect a redacted case. | P and S |
| Which wind measurements actually change decisions? | Record on-site measurements separately from regional weather and flight-controller estimates. | W and D |
| Can source data and review decisions be traced? | Provenance, timestamps, units, altitude basis, reviewer and revision state. | D, W and S |

Do not imply that a large vendor lacks a feature without first asking the operator. For W, spraying is the strongest early validation case because a field weather window is part of the public operation record; search and inspection primarily need operational-condition context unless a partner identifies a more specific wind decision.
