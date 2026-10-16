# MEGA Renamer

A self-hosted MEGAcmd workspace. Import a public MEGA file or folder link into your signed-in account, remove configured filename tags, preserve a text manifest, and return public links for every file. React UI with shadcn-style button components, Radix UI primitives/icons, and Tailwind CSS. The Python API has no third-party runtime dependencies.

## Run

```sh
cp .env.example .env
# Replace API_TOKEN with a long random token, e.g. from openssl rand -hex 32.
docker compose up --build -d
docker compose exec renamer mega-cmd
```

In the MEGAcmd shell, enter `login your-email@example.com`, then follow the password and MFA prompts. Use `exit --only-shell` to leave the shell while keeping the server running. Login is performed inside the container; credentials never pass through the web interface. The account session and jobs persist in separate Docker volumes.

Open http://localhost:8080 and enter the API token from `.env`. Paste a full MEGA link including its decryption key. Each import creates `/Imports/<job-id>` in your account. Files are imported server-side without downloading their contents locally. Original names, planned names, and removed matches are written as JSON lines in `original-filenames.txt`, uploaded before renaming. The report sits at the import job folder root alongside the imported content. The UI shows progress, original/cleaned names, report and folder links, and a copy-links action.

The image uses `python:3.12-slim-bookworm`, installs the official amd64 MEGAcmd 2.6.0 package with SHA-256 verification, and runs as a non-root user under tini. Node is only used in the UI build stage. Compose selects amd64 because this MEGAcmd package is amd64; ARM hosts require emulation. Update the Dockerfile version and checksum together when upgrading.

## Automatic image updates

[The MEGAcmd image workflow](.github/workflows/megacmd-image.yml) checks the official Debian 12 amd64 package index daily at 03:23 UTC. Add the workflow to your GitHub repository's default branch to enable the schedule. GitHub schedules can run late; see [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

When the package version has no published image yet, the workflow builds and pushes `ghcr.io/<owner>/<repo>:latest` and `ghcr.io/<owner>/<repo>:megacmd-<version>` for `linux/amd64`. The first check also publishes the current version. Builds pass the repository's version and SHA-256 checksum to the Dockerfile; the checked-in defaults remain pinned for local builds. A failed build is retried on the next daily check because only successfully published version tags count as complete.

Publishing uses the built-in `GITHUB_TOKEN` with `packages: write`; no registry secret is required. The repository must allow GitHub Actions to publish packages. Package visibility is managed in GitHub's package settings. Use **Actions → Poll MEGAcmd and publish image → Run workflow** to check immediately, or select **force** to rebuild the current package after application changes. Application commits do not trigger this workflow automatically.

To use the published image, replace `build: .` in `compose.yaml` with `image: ghcr.io/<owner>/<repo>:latest`, then run `docker compose pull && docker compose up -d`. Publishing an image does not update running containers automatically.

## API

All application endpoints require `Authorization: Bearer <API_TOKEN>`; only `/api/health` is public.

```sh
curl http://localhost:8080/api/jobs \
  -H "Authorization: Bearer $API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://mega.nz/folder/HANDLE#KEY"}'

curl http://localhost:8080/api/jobs/JOB_ID \
  -H "Authorization: Bearer $API_TOKEN"
```

`POST /api/jobs` returns HTTP 202 with the job ID. Poll `GET /api/jobs/<id>` until `complete` or `failed`. Completed jobs contain `files[].url`, `manifestUrl`, and `folderUrl`. `GET /api/jobs` returns the most recent 30 jobs; `GET /api/account` reports session connectivity. Jobs are serialized to avoid account command races; a bounded queue allows 100 pending requests. Every queued import checks current storage before creating its destination. A restart marks unfinished jobs failed instead of silently importing duplicates. A failure retains any import folder, audit report, and already-generated links for review; resubmitting starts a separate import.

## Cloud storage and trash

The **Cloud storage** card shows available bytes, used/total storage, and rubbish-bin usage. Storage is read using `mega-df`, cached for up to 30 seconds for display, and refreshed for capacity checks. Trash still counts toward the account storage limit until permanently deleted. Account totals may take time to reflect changes made at MEGA.

Use **Check size** beside a public link to compare its size plus a report reserve with available space. Import submission checks capacity too, and the worker checks again immediately before creating a cloud folder. File/folder metadata is read using MEGA's public-link metadata API without switching the signed-in MEGAcmd session or downloading file contents. If size or quota cannot be determined, the import is blocked with a visible error. The reserve is at least 1 MiB, or 4096 bytes per source file if larger; the actual report size is checked against remaining space before upload. External account activity or changes to a source link can still change quota after a check; MEGA's import result remains authoritative.

Select a completed or failed import to use **Trash import**. This moves its whole destination folder to `//bin` using the folder's node handle. **Empty trash** permanently deletes all current top-level rubbish-bin nodes, including unrelated files. **Trash & empty trash** performs both operations in sequence and also empties the entire account rubbish bin. A confirmation dialog explains the scope before either permanent action. These actions are rejected while an import or another trash operation is running. Emptying is a sequence of remote deletions, so a failure can leave part of the trash undeleted; successful deletions remain recorded. Trashed/deleted jobs retain their logs and filename records, and their stored public links are cleared. Failed capacity checks that created no destination do not show import-trash controls.

Additional authenticated endpoints:

| Endpoint | Behavior |
| --- | --- |
| `GET /api/storage` | `usedBytes`, `totalBytes`, `availableBytes`, `trashBytes`, `checkedAt` |
| `POST /api/import-check` with `{"url":"…"}` | Source size, report reserve, required/available bytes, `fits`, and `shortfallBytes` |
| `POST /api/jobs/<id>/trash` with `{}` | Move the import folder to account trash |
| `POST /api/trash/empty` | Permanently empty the account trash |
| `POST /api/jobs/<id>/trash-empty` | Trash the selected import and permanently empty account trash |

Both permanent endpoints require `{"confirm":"EMPTY_ACCOUNT_TRASH"}`. Trash operations return HTTP 409 if an import is running. Jobs moved to trash have status `trashed`; after permanent removal they have status `deleted`.

## Naming rules

Default filtered strings live in [`backend/naming-rules.json`](backend/naming-rules.json). On first startup, this file is copied to `/data/naming-rules.json` in the persistent jobs volume. Existing saved configuration is preserved on restarts and image upgrades.

Connect to the web workspace and edit **Naming rules**. Enter one literal string per line in **Always remove** or **Remove only after a resolution**, then click **Save rules**. **Discard changes** restores the last saved version. Empty lists disable the corresponding filters. Matching ignores case; punctuation is literal, not a regular expression. Duplicate strings, empty entries, slashes, control characters, oversized lists, and unsupported JSON versions are rejected by the API. Saves replace the JSON file atomically.

```json
{
  "version": 1,
  "remove": ["WEB-DL", "WEBRip", "WEB.x264"],
  "afterResolution": ["BluRay.DTS", "BluRay.DTS-HD"]
}
```

The editor is backed by authenticated `GET /api/rules` and `PUT /api/rules` endpoints. Newly submitted jobs snapshot the saved rules; changing the configuration does not alter queued/running imports or previously renamed files. Conditional strings require a 3–4 digit `p` resolution immediately before them, separated by a dot; the resolution is preserved.

The default case-insensitive whole tags removed are `WEB-DL`, `WEBRip`, `BDRip`, `HDRip`, `DVDRip`, `WEB.x264`, `WEB.h264`, `HDTV.x264`, `HDTV.XviD`, and `BluRay.x264`. By default, `BluRay.DTS` and `BluRay.DTS-HD` are removed only directly after a 3–4 digit `p` resolution, with the resolution retained. Codec suffixes such as `.MA.5.1` remain.

Examples:

| Original | Result |
| --- | --- |
| `Film.1080p.WEB-DL.mkv` | `Film.1080p.mkv` |
| `Film.2160p.BluRay.DTS-HD.mkv` | `Film.2160p.mkv` |
| `Phone.Booth.2002.BluRay.DTS-HD.MA.5.1.mkv` | unchanged |
| `REMUX.BluRay.DTS.mkv` | unchanged |
| `BluRay.1080p.DTS.mkv` | unchanged |

Files without matching tags remain unchanged. Folder names remain unchanged. Separator runs left after removal are collapsed; extensions are preserved. Collisions receive `(2)`, `(3)`, etc. A matching basename that becomes empty uses `untitled`.

Files are selected for renaming and exporting using their MEGA node handles. Square brackets and wildcard characters in filenames are supported; rename destinations use literal path lookup. Imports with backslashes, colons, line breaks, or duplicate paths fail for manual review because the CLI listing/path format cannot safely represent them here. Password-protected links and links to selected subnodes are not supported. Generated exports are public links, including the original-name manifest. MEGA export terms are accepted by the service via `mega-export -f`.

## Errors and activity logs

Use **Remove from history** on a finished import to delete its saved record, logs, filenames, and links from this workspace. **Clear history** removes all finished records, including older entries beyond the 30 shown in the UI. Both actions require confirmation and leave cloud files in MEGA. Queued/running records cannot be removed; history changes are rejected while an import or trash operation is running to prevent records being recreated by an in-flight operation. Use the existing trash controls when you also want to remove cloud files.

The authenticated endpoints are `DELETE /api/jobs/<id>` for one finished record and `DELETE /api/jobs` for all finished records. They return `removedRecords`; unknown IDs return 404 and active operations return 409.

Select an import in **Recent imports** to see its destination, failure message, and timestamped activity log. Logs update automatically and persist with the job. They include processing stages, command start/completion, removed tags, and command failures with exit codes and diagnostic output. The latest 500 entries are retained per job. Application logs redact URLs, source-link keys, API tokens, and email addresses; MEGAcmd's own container logs are separate. Older jobs show their saved error but cannot reconstruct logs from before this feature was added.

```sh
docker compose logs --tail=200 renamer
docker compose logs -f renamer
```

After source changes, rebuild with `docker compose up --build -d`. Existing failed jobs remain failed; a new submission creates a new import folder.

Compose binds to loopback. For remote access, place the app behind an HTTPS reverse proxy and retain authentication. Set `X-Forwarded-Proto: https` at the proxy so browser session cookies receive the `Secure` flag. Source links contain decryption keys and job records contain public exports; protect the persistent data volume. Avoid running other rename operations inside a job folder while processing.

The web workspace remembers your login for 30 days using an HttpOnly, SameSite=Strict cookie. The API key is used to establish the session and is not saved in browser storage. Sessions are stored as hashes in the persistent jobs database, survive container restarts, and expire automatically. **Sign out** in the header revokes the current browser session without logging your account out of MEGAcmd. Changing `API_TOKEN` invalidates existing browser sessions. API clients can continue to use bearer authentication; browser sessions use `POST`, `GET`, and `DELETE /api/session` to connect, restore, and sign out.

## Development and checks

```sh
python3 -m unittest discover -s tests -v
cd web
npm ci
npm run build
```

For local development, run the Python server with `API_TOKEN`, `DATA_DIR`, and `STATIC_DIR` set, and run `npm run dev` in `web`. Vite proxies `/api` to port 8080. MEGAcmd must be installed and signed in on the host for real imports.

MEGAcmd command references: [import](https://github.com/meganz/MEGAcmd/blob/master/contrib/docs/commands/import.md), [export](https://github.com/meganz/MEGAcmd/blob/master/contrib/docs/commands/export.md), [find](https://github.com/meganz/MEGAcmd/blob/master/contrib/docs/commands/find.md), [move](https://github.com/meganz/MEGAcmd/blob/master/contrib/docs/commands/mv.md).

## Themes

Use the **Theme** picker in the header to choose Mist (default), Dusk, Pebble, Linen, MEGA, or MEGA Dark. Mist, Dusk, Pebble, and Linen use soft sage, lavender, and earth tones. MEGA retains its red-and-white palette; MEGA Dark pairs the same red accents with charcoal surfaces. Your choice is saved in browser storage and restored on your next visit. Preset colors are defined in `web/src/themes.json`.
