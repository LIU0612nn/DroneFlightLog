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
