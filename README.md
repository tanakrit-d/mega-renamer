# MEGA Renamer

A self-hosted web app that cleans up MEGA filenames for use with debrid services. Release tags such as `WEB-DL` and `BluRay.DTS-HD` can interfere with filename matching; MEGA Renamer removes configured tags while preserving the title, resolution, and file extension. Adjust the rules to suit your debrid service's naming requirements.

## How it works

Paste a public MEGA file or folder link, including its decryption key. The app imports it into `/Imports/<job-id>` in your signed-in MEGA account, cleans the filenames, and generates public links you can copy into your debrid service. File contents stay in MEGA and are imported server-side, without downloading them to your host.

Each import includes an `original-filenames.txt` report recording the original names, planned names, and removed tags. The web interface shows progress, activity logs, and links to the files, folder, and report. Imports run one at a time. Failed imports keep any files already imported for inspection; retrying creates a separate import.

## Setup with Docker Compose

Install Docker with Compose, then clone this repository and create your configuration:

```sh
git clone https://github.com/tanakrit-d/mega-renamer.git
cd mega-renamer
cp .env.example .env
openssl rand -hex 32
```

Set `API_TOKEN` in `.env` to the generated token, then build and start the app:

```sh
docker compose up --build -d
docker compose exec renamer mega-cmd
```

In the MEGAcmd shell, enter:

```text
login your-email@example.com
```

Follow the password and MFA prompts, then leave the shell with:

```text
exit --only-shell
```

Open [http://localhost:8080](http://localhost:8080), enter your API token, and paste a MEGA link to start. MEGA credentials are entered inside the container; they never pass through the web interface.

Compose stores the MEGA session and job data in separate persistent volumes, so they survive container restarts and replacements. Avoid `docker compose down -v` unless you intend to delete those volumes. The image targets `linux/amd64`.

The default port is accessible only from the Docker host. For remote access, use an HTTPS reverse proxy that sets `X-Forwarded-Proto: https` and keep API-token authentication enabled.

## Naming rules

Edit **Naming rules** in the web interface, with one literal string per line:

- **Always remove** removes matching whole tags wherever they occur. Defaults include `WEB-DL`, `WEBRip`, `BDRip`, `HDRip`, `DVDRip`, `WEB.x264`, `WEB.h264`, `HDTV.x264`, `HDTV.XviD`, and `BluRay.x264`.
- **Remove only after a resolution** removes tags immediately after a dotted resolution such as `1080p.` or `2160p.`. Defaults are `BluRay.DTS` and `BluRay.DTS-HD`.

Matching ignores case and treats punctuation literally. The app preserves folder names and file extensions, tidies separators left by removed tags, and adds `(2)`, `(3)`, etc. when cleaned names collide.

| Original | Cleaned name |
| --- | --- |
| `Film.1080p.WEB-DL.mkv` | `Film.1080p.mkv` |
| `Film.2160p.BluRay.DTS-HD.mkv` | `Film.2160p.mkv` |
| `Film.2002.BluRay.DTS-HD.MA.5.1.mkv` | Unchanged: no resolution immediately before the tag |

Click **Save rules** to apply changes to newly submitted imports. Saved rules persist across restarts and upgrades; existing jobs retain the rules they started with. Empty either list to disable that filter.

## Storage and trash

Imports use storage in your MEGA account. The **Cloud storage** card shows used, available, and rubbish-bin storage. **Check size** compares a link's size, plus space for the filename report, against your available quota. Capacity is checked again before importing; imports are blocked if size or quota cannot be determined.

- **Trash import** moves the selected import's entire folder to your MEGA rubbish bin. This does **not** free storage yet.
- **Empty trash** permanently deletes **everything in your account's rubbish bin**, including unrelated files.
- **Trash & empty trash** moves the selected import to the bin, then permanently empties the entire bin.

Permanent deletion requires confirmation. Storage totals may take time to update. Trashed imports keep their local logs and filename records, but their saved public links are cleared.

**Remove from history** and **Clear history** delete local job records only; they leave files in MEGA. Use the trash controls to remove cloud files.

## Updates and troubleshooting

To update a local build after pulling changes:

```sh
git pull
docker compose up --build -d
```

The [GitHub workflow](.github/workflows/megacmd-image.yml) checks daily for new MEGAcmd packages and publishes images to `ghcr.io/<owner>/<repo>` with `latest` and `megacmd-<version>` tags. To use a published image, replace `build: .` in `compose.yaml` with `image: ghcr.io/<owner>/<repo>:latest`, using the publishing repository's owner and name. Then update with:

```sh
docker compose pull
docker compose up -d
```

New images do not automatically replace running containers. Your session, rules, and history remain in the persistent volumes.

For failures, open the import's activity log or inspect the container logs:

```sh
docker compose logs --tail=200 renamer
```

Use full public file or folder links; password-protected links and links to selected subnodes are unsupported. Generated links, including the filename report, are public, so share them carefully.
