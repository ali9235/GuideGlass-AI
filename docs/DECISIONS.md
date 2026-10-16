# GuideGlass AI: engineering decisions

These explain the **current inspectable design/documentation**, not why the owner originally bought components. Original selection history and personal debugging experiences have not been supplied.

| Decision | Current-file rationale | Alternative / trade-off | Constraint |
| --- | --- | --- | --- |
| Windows worker and browser view | Keep inference/map state on Windows and render in a lightweight client. | On-phone inference needs a separate compatibility/performance study. | Windows availability and physical Safari performance remain constraints. |
| Observed points and depth provenance | Project actual inputs and reject unusable frames rather than invent unseen surfaces. | Generated completion can look convincing without being observed. | Monocular scale, calibration and drift limit accuracy; no loop optimization. |
| Bounded non-pickle storage | Validate ids, shapes and archive sizes with allow_pickle=False. | Pickle is convenient but executable; a database adds complexity. | Files remain sensitive/unencrypted and reload is view-only. |
| Local models; separate downloads | Inference loads installed local weights. | Hosted inference adds transfer, keys and cost. | Browser speech/recognition has separate device/vendor privacy behavior. |

## Challenges: distinguish observed from suggested

The distance HTTP 502 is an actual observed failure, but its root cause and successful repair are **not established**. Regression tests show specific software protections, not an invented account of the owner's original debugging.

Earlier camera transport succeeded; distance returned HTTP 502. No established root cause/fix, wearable ranging result, audible-effectiveness study, physical Safari validation or safe navigation result.

Troubleshooting suggestions are hypotheses, not incidents already solved. Add a case study only with the observed symptom, reproducible conditions, evidence for the cause, exact change, before/after test and remaining uncertainty. Do not turn design intentions into measured improvements.

[Architecture](ARCHITECTURE.md) · [Validation record](VALIDATION.md)
