# Synthetic test logs

All four CSV files are generated examples, not real drone flights or evidence. Upload each file through its matching page:

- `performance.csv` → `/start/performance`: normal route, altitude and speed.
- `incident.csv` → `/start/incident`: fabricated speed and altitude excursion near sample 50 for testing the evidence draft; this is not a diagnosed incident.
- `wind.csv` → `/start/wind`: fabricated logged wind telemetry. The site labels logged wind as unverified. The external model profile may be unavailable when the weather API has no data.
- `team.csv` → `/start/team`: routine sample for the team handoff form. Enter organization/project labels in the form.

Coordinates are in the Los Angeles area and timestamps are UTC. The files are intended only for UI and parser testing.
