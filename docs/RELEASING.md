# GuideGlass AI: version history and releases

## Version boundary

Proposed candidate: **v0.1.0-docs.1** — a documentation/reference package, **not commissioned hardware v1.0.0**. This page alone creates no Git tag or GitHub Release. Do not move an existing tag.

Use patch versions for compatible corrections, minor versions for compatible capability, and a major version for incompatible public contracts. Track hardware/wiring revisions separately.

## Release checklist

1. Review the [changelog](../CHANGELOG.md), exact paths and repository URL. Obtain owner approval of the publication scope.
2. Run [validation](VALIDATION.md); retain dates and failed/blocked checks. Missing physical tests never count as passes.
3. Review Git export/history, media and configuration for sensitive content using the [security model](../SECURITY.md).
4. Check Markdown links, source references, diagrams and original-image integrity. No diagram may imply unverified wiring.
5. Preserve default hardware gates and scope. No flashing or actuation belongs in a documentation release.
6. Review staged changes, commit normally and push only the approved branch. Never force-push unrelated work.
7. After explicit tag/release approval, verify the target commit, create an annotated candidate tag and matching release notes; verify the remote tag/assets.
8. Inspect rendered documentation and CI results. Report pending/failed checks without a fabricated green badge.

Release notes must state changes, revision, software results with limits, actual hardware evidence (or its absence), blockers and license status. No new project-wide license has been selected.

## Recovery

Correct unsupported claims with a reviewed revert/fix commit. Do not reset shared history. Revoke/rotate leaked credentials separately; history removal requires explicit scope and approval.

[Official GitHub release guidance](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) describes the platform. VOLTRA Engineering Standard is project-maintained, not GitHub certification.
