# Studio Viet workspace v0.5 release status

Verified September 23, 2026. This is a status/handoff document, not the application's source upload or a deployment receipt.

## Existing release

The owner has `Studio-Viet-v0.5-Public-Source.zip`, containing the generic source, backend handlers, tests, and developer documentation. Its SHA-256 is `e90833f8bbb81769aff44564bd1f035af45f7d142049cc8bf8c7c0e5e31863cd` (129,933 bytes). The source manifest identifies local revision `02061adcb2eebbb9b818d8f29d276879acb9e49b`.

The source was restored and checked again in this session:

- 120 Node state, server, report-delivery, and permission-boundary tests passed.
- 19 rendered-document browser scenarios passed.
- JavaScript syntax checks and the generic production build passed.
- The built single-file frontend is 205,676 bytes.
- Browser scenarios use simulated storage and provider responses. They do not establish real browser durability, live credential access, a security audit, or hosted deployment.
- A targeted scan found no private project catalog, personal account details, or token-like credentials in the generic source.

## Remote state

The branch `feature/morning-delivery-v05` contains a staged source-import workflow. Its first run failed while downloading an expired temporary archive URL, before source files were committed. Run: https://github.com/StudioViet/StudioVietProjects/actions/runs/35859933732

A later importer update was blocked by a safety check. It was not applied and was not bypassed. The failed importer is left unchanged. Do not claim the complete source is present in this repository, and do not rerun that expired importer.

The connected Vercel deployment action returned `Tool deploy_to_vercel not found`. No deployment ID or verified hosted URL was returned. More repository permissions alone do not resolve an unavailable deployment action.

## Frontend versus execution

The local app has project workspaces, larger typography, Back controls, task management, draft review, editable project guidance, app links, mission plans, and local timeblocks.

The v0.5 backend is a single-owner, read-only morning-report gateway. It includes `/api/status`, `/api/session`, `/api/morning`, and `/api/agents/status`. It does not run autonomous agents, move money, send outreach, publish campaigns, or perform paid model calls.

Existing external scheduled work remains separate. A recorded task run and a saved artifact are the evidence for completion, not a green badge or a plan in the frontend.

## Remaining deployment work

1. Transfer the actual reviewed generic source archive contents into a review branch. Do not upload personalized HTML, browser backups, a private catalog, `.env`, or credentials. Preserve the repository's original README/history.
2. Run `npm run check`, `npm test`, and `npm run build` on the actual uploaded source. Review the diff before merging.
3. Import the repository into the intended Vercel account. The prepared configuration uses `npm run build`, output directory `dist`, and the included `/api` functions. Verify the deployment URL and basic navigation.
4. Leave report access disabled until the owner configures `APP_ORIGIN`, `WORKSPACE_ACCESS_KEY`, `NOTION_API_KEY`, and `NOTION_CONTROL_PAGE_ID` in server-side host settings. Never put provider credentials in a frontend sign-in field or a repository file. The owner access key is distinct from provider keys.
5. Verify anonymous denial, owner sign-in, sign-out, profile switching, the selected report source, and a real scheduled result appearing in the UI. Do not call this complete from simulated test results alone.

No source upload, public deployment, user notification, or unattended execution is implied by this document's commit.
