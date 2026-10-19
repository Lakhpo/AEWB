# Development instructions

## Project context and scope

- Read [PROJECT.md](PROJECT.md) before planning or changing application behavior. It defines Pet Project's vision, requirements, proposed architecture, and phased roadmap.
- Current scope includes satellite navigation, AOI selection/export, Microsoft building analysis, manual building corrections/planning, and a separate Overture road layer with optional OSM reference roads. Keep easements, road editing/planning, additional engineering analysis, custom models, architecture changes, and deployment deferred until requested.
- Develop and validate one phase at a time. Do not implement later phases, custom computer vision, or a framework migration without a request.
- Treat proposed technologies and future capabilities as plans, not existing functionality. Keep documentation accurate as work progresses.

## Architecture

- Preserve the existing `src/geoanalysis` layout. Use `ui/app.py` for Streamlit, `core/geometry.py` for AOI and coordinate handling, `services/buildings.py` for Microsoft footprint access, `services/imagery.py` for future imagery access, and `analysis/analysis.py` for processing.
- Do not create a parallel `backend` directory or reorganize the repository without a concrete need and user direction.
- Keep backend modules independent of Streamlit widgets and session state. Define clear input/output contracts when implementing each phase.
- Keep exploratory notebooks separate from reusable production modules.

## Implementation principles

- Favor readable, documented Python and small, focused functions. Add dependencies only when the active phase needs them; record runtime dependencies in `requirements.txt`.
- Prioritize open-source tools, low-cost operation, and compatibility with eventual public deployment.
- Prefer established geospatial datasets before custom models. Evaluate rural as well as urban coverage; disclose coverage gaps and uncertainty.
- Label matches as buildings/footprints, not verified houses. Count unique footprints with interior overlap with the AOI once; exclude boundary-only touches. Invalidate counts and overlays when AOI geometry changes. Do not turn network, coverage, or resource-limit errors into a zero count or silently present partial counts.
- Keep AOI boundaries separate from building edits. Preserve the original Microsoft result and stable source IDs; maintain a working review with provenance and existing/planned status. Exclude plans from existing-building counts, retain valid corrections on same-AOI source refresh, and allow undo. Validate edits before updating counts/exports. Make session-only storage and download requirements clear.
- Road loading must preserve the Microsoft building workflow, map viewport, and AOI. Keep roads outside editable feature groups. Query worldwide sources using AOI bounds; invalidate road results when AOIs change. Preserve source attributes/license metadata and clip centerlines to the AOI. Keep Overture and OSM reference counts/lengths and downloads separate because the sources overlap. Do not infer public access or easement rights. Bound network work and use geodesic measurements for lengths.
- Validate AOIs before processing. Use WGS 84 longitude/latitude order for GeoJSON and explicit CRS handling for spatial operations. Do not perform metric calculations directly on geographic degrees.
- Check provider licensing, attribution, access requirements, and redistribution terms when selecting imagery or datasets.
- Keep credentials out of source control. Keep large imagery, bulk datasets, and generated outputs out of the repository; use small redistributable samples for validation.
- Surface actionable input, data-access, and processing errors in the UI as those features are introduced.

## Validation and documentation

- Validate the active phase against its acceptance criteria in `PROJECT.md` before proposing the next phase.
- Use focused tests for meaningful geometry and analysis behavior, and manually check interactive map behavior when implemented. Documentation-only work needs content and diff review, not application tests.
- Report what changed, what was checked, and any unresolved limitations. Do not claim unrun tests or unimplemented capabilities.
- Update `PROJECT.md` when scope or architectural decisions change; maintain detailed design decisions in `docs/architecture.md` and user-facing setup/run instructions in `README.md` when applicable.
- Preserve unrelated existing work. Do not deploy or add infrastructure as part of an earlier phase.
