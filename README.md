# Tweetos

A skill for writing tweets in your own voice, using your local X history and a build in public strategy. Compatible with Codex and Claude.

The skill prepares drafts, replies, threads, and content calendars. Its editorial guidelines focus on sharing real progress, staying authentic, and providing useful content.

**Current status:** editorial guidelines, archive import, and tweet search are available. Each installation has its own configurable X account and history folder. No personal tweet history is included in this repository.

## How do I provide my tweet history?

**The input is the ZIP file of your X archive**, downloaded from your account. Give its file path to Codex or Claude Code, or pass it to the import script with `--archive`. See [Add your tweet history](#add-your-tweet-history) for the full walkthrough.

The workflow is:

1. Download your X archive to your computer.
2. Import the ZIP to create `tweets.jsonl` and `corpus-summary.json`.
3. Ask Codex or Claude Code to analyze these tweets and create `style.md`.
4. For the Telegram bot, place these **three files** in a folder accessible to Docker, selected with `TWEETOS_HISTORY_DIR`.
5. Send `/status` to the bot, then send your ideas as text messages.

| Item | What you provide |
|---|---|
| Input archive | A local ZIP file, selected by its path with `--archive` |
| Expected account | Your X username, passed to `--account` during import and `TWEETOS_X_ACCOUNT` in `.env` |
| History used by the bot | A folder containing the three prepared files, selected with `TWEETOS_HISTORY_DIR` |
| Ideas to rewrite | Text messages in Telegram after setup is complete |

**Uploading the ZIP through Telegram is not supported.** Setting a username does not automatically download tweets. Importing prepares the tweet dataset; creating the style profile is a separate step with an assistant that can access your files. Each installation supports one authorized Telegram user and their history.

## Install the skill

### Claude

- **Claude.ai:** download [dist/tweetos.zip](dist/tweetos.zip), upload it in the Skills section, and enable the skill. Code execution must be available to run the Python scripts. See the [official documentation](https://support.claude.com/en/articles/12512180-use-skills-in-claude).
- **Claude Code:** place the repository contents in `~/.claude/skills/tweetos/`, with `SKILL.md` directly inside that folder. Invoke `/tweetos` or request a writing task matching its description. See the [official documentation](https://code.claude.com/docs/en/skills).

### Codex

Place the repository contents in `~/.codex/skills/tweetos/`, or in the `skills/tweetos` folder under your `CODEX_HOME`, then invoke `$tweetos`.

The `agents/openai.yaml` file provides Codex interface metadata. The instructions, references, and scripts are self-contained and do not require an X connector.

## Run the Telegram bot with Docker and OpenAI

The service receives your private Telegram messages, loads the skill's rules and your style profile, then calls the OpenAI API to reply in Telegram. It keeps the last six exchanges in the persistent `data/` folder so you can request revisions. It uses long polling: no domain name or incoming HTTP port is needed, only outbound HTTPS access to Telegram and OpenAI.

### Prepare the bot and API access

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the instructions. Keep the token for your `.env` configuration file.
2. Open a conversation with your new bot and send `/start`.
3. Prepare an OpenAI API key and the exact ID of a text model available to your API project that supports the Responses API. Set the model with `OPENAI_MODEL`.

Sources: [creating Telegram bots](https://core.telegram.org/bots/features#botfather), [long polling](https://core.telegram.org/bots/api#getupdates), [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create).

### Start with Docker Compose (recommended)

Everyone who clones the repository uses their own Telegram bot, OpenAI key, and tweet history. Secrets and personal data are excluded from the repository and Docker image.

The bot can run on **your computer, a NAS that supports Docker Compose, or a server**, including a VPS. You need a running Docker engine, Docker Compose, persistent storage, and outbound HTTPS access. The machine must stay on and connected for the bot to respond.

Install [Docker Desktop](https://docs.docker.com/desktop/) on your computer, or Docker Engine and Compose on your Linux machine, for example using the [official Debian instructions](https://docs.docker.com/engine/install/debian/). On a NAS or container platform, use its interface to deploy the Compose project and mount the persistent folders. Platforms without Compose or bind mount support require deployment adjustments.

In a terminal on the machine where you manage the Docker project:

```sh
git clone https://github.com/cbsaasbuilder-oss/tweetos.git
cd tweetos
```

Prepare the configuration and folders for your environment.

**Windows / PowerShell with Docker Desktop:**

```powershell
Copy-Item deploy/tweetos.env.example .env
New-Item -ItemType Directory -Force data/references | Out-Null
notepad .env
```

**Linux / macOS:**

```sh
cp deploy/tweetos.env.example .env
chmod 600 .env
mkdir -p data/references
nano .env
```

On Linux with a standard Docker Engine installation, assign the data folder to the container's user:

```sh
sudo chown -R 10001:10001 data
sudo chmod 700 data data/references
```

The commands below use `docker compose`. On Linux, prefix them with `sudo` if your Docker setup requires it. With Docker Desktop, run them directly. For a NAS or another Docker setup, grant the container user (UID/GID `10001:10001`) the required permissions on mounted folders through your environment's settings.

Fill in `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, and `OPENAI_MODEL`, for example `gpt-4.1-mini` if your project has access to it. Leave `TELEGRAM_ALLOWED_USER_ID` unchanged for now. Never commit `.env` to Git. Docker Compose sets the internal storage paths; data is stored in `data/` on the host.

Configure your X account and history folder in `.env`:

```ini
TWEETOS_X_ACCOUNT=your_username
TWEETOS_HISTORY_DIR=./data/references
```

`TWEETOS_HISTORY_DIR` is a host path, either absolute or relative to `compose.yaml`. This folder should contain `tweets.jsonl`, `corpus-summary.json`, and, after analysis, `style.md`. You can select another private folder without changing the code or skill. The bot mounts it as read-only. A username alone does not download tweets.

Build the image from the repository folder:

```sh
docker compose build
```

If you selected a different `TWEETOS_HISTORY_DIR`, create that folder and make it readable by UID/GID `10001:10001` before running Compose. Keep personal history files out of the public repository wherever you store them.

Send `/start` to your bot in Telegram, then retrieve your user ID:

```sh
docker compose run --rm tweetos --identify
```

For a new bot that only you have messaged, the displayed number is yours. If no number appears, send `/start` again to the correct bot. If several IDs appear, identify yours before continuing. Set `TELEGRAM_ALLOWED_USER_ID` to that number in `.env`, then start the bot:

```sh
docker compose run --rm tweetos --check
docker compose up -d
docker compose logs --tail=50 tweetos
```

`--check` validates local files and settings without calling OpenAI. Send a writing request to the bot to test an actual generation. Only one instance should use the token: stop any existing systemd service before starting Compose (`sudo systemctl disable --now tweetos`).

The container runs as an unprivileged user, exposes no ports, and restarts automatically with Docker. The `data/` folder preserves conversation state and, with the default history path, your profile after the container is removed.

To personalize the writing style, follow [Add your tweet history](#add-your-tweet-history). It covers importing on your computer, creating a profile, and placing the files in the folder mounted by Docker. A transfer is needed only when Docker runs on another machine. You can also complete these steps before starting the bot for the first time. Without these files, the bot uses only the editorial guidelines and your writing briefs.

If you are migrating from systemd, stop that service, copy the contents of `/var/lib/tweetos/` into `data/`, and assign them to UID/GID `10001:10001`. Reference files are reread for each request.

Common commands, run from the repository folder:

```sh
docker compose logs --tail=50 tweetos
docker compose restart tweetos
docker compose down
# Update and rebuild; data/ and .env are preserved.
git pull --ff-only
docker compose up -d --build
```

When you change accounts or history folders, the bot clears its conversation context and last draft at startup to avoid mixing profiles. Tweet files and Telegram update tracking are preserved.

After editing `.env`, use `docker compose up -d --force-recreate` to load the new settings. For a consistent SQLite backup, stop the bot with `docker compose stop`, back up `data/` and `.env` to a private location, then resume it with `docker compose start`. Include your history folder in the backup if it is outside `data/`.

### Alternative without Docker: systemd on Linux

These commands assume a new installation in `/opt/tweetos`. Python 3.9 or newer is sufficient; no additional Python packages are required.

```sh
sudo apt-get update
sudo apt-get install -y python3 git ca-certificates
sudo git clone https://github.com/cbsaasbuilder-oss/tweetos.git /opt/tweetos
sudo useradd --system --user-group --home-dir /var/lib/tweetos --shell /usr/sbin/nologin tweetos
sudo install -d -m 700 -o tweetos -g tweetos /var/lib/tweetos/references
sudo install -m 600 /opt/tweetos/deploy/tweetos.env.example /etc/tweetos.env
sudo nano /etc/tweetos.env
```

Replace the `REPLACE_...` values in `/etc/tweetos.env`:

| Variable | Expected value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token provided by BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | Your **numeric** Telegram user ID; an `@username` is not sufficient |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | Exact ID of the selected model |
| `TWEETOS_X_ACCOUNT` | Target X username without `@`; leave empty if unspecified |
| `TWEETOS_HISTORY_DIR` | Docker: history folder on the host |
| `TWEETOS_PERSONAL_DIR` | systemd: history folder on the Linux machine |
| `OPENAI_MAX_OUTPUT_TOKENS` | Output limit per generation, 1,800 by default; includes reasoning tokens for models that use them |

To find your Telegram ID after sending `/start`, fill in the bot token first, then run this command before starting the service:

```sh
sudo python3 /opt/tweetos/scripts/telegram_bot.py --env-file /etc/tweetos.env --identify
```

It lists the sender IDs of pending private messages without acknowledging those messages. For a new bot that only you have messaged, the displayed number is yours. If several IDs appear, identify yours before configuring access. Set `TELEGRAM_ALLOWED_USER_ID` in the file. Do not run this command while another process is using the same bot.

Once all values are configured:

```sh
sudo python3 /opt/tweetos/scripts/telegram_bot.py --env-file /etc/tweetos.env --check
sudo install -m 644 /opt/tweetos/deploy/tweetos.service /etc/systemd/system/tweetos.service
sudo systemctl daemon-reload
sudo systemctl enable --now tweetos
sudo systemctl status tweetos
```

`--check` validates only local configuration and reference files. Your first writing request tests model access. The service replies only to the authorized user in a private conversation and ignores groups and other users.

### Chat with the bot

Send your brief as text, for example: "Today I finished the search feature in my app. Write a straightforward tweet about it." Follow up with "Make it shorter" or "Try another angle."

- `/help`: show help.
- `/status`: check whether the profile and history are present.
- `/last`: retrieve the last draft without another OpenAI call.
- `/reset`: clear the service's conversation context and last draft; keep the style profile and messages already in Telegram.

Place the imported history (`tweets.jsonl`, `corpus-summary.json`) and profile (`style.md`) in `TWEETOS_HISTORY_DIR` for Docker (`data/references` by default, UID/GID `10001:10001`), or in `/var/lib/tweetos/references` for systemd (user `tweetos`). Use the import procedure below with your chosen output folder. Create the profile with an assistant that can access your files, then place it in the configured history folder. These references are reread for each generation; replacing their contents does not require a restart.

For each request, the bot loads your style profile and selects up to six historical tweets, ranked by word overlap with your idea and then by recency. These examples guide tone, vocabulary, rhythm, and formatting. The facts of the new draft must come from your current brief, not from old tweets. This uses reference material at generation time; it does not train or fine-tune a model.

Without a profile, the bot can draft from your brief and the guidelines, but does not claim to know your personal voice. Recent exchanges, your profile, and a few relevant tweet examples are sent to the OpenAI API to generate a response. The service uses `store=false` and manages context locally. This does not guarantee that providers retain no data.

This version supports text only: it cannot read links, browse the web, import attachments, or publish on X. For news, provide the source content; the bot cannot independently verify whether it is current. A Telegram token, an OpenAI key, and an active runtime are required.

### Operations and troubleshooting

With systemd (for Docker, use the Compose commands above):

```sh
sudo journalctl -u tweetos -n 50 --no-pager
sudo systemctl restart tweetos
sudo systemctl stop tweetos
```

When the systemd service is enabled, the bot starts again after the Linux machine reboots. Run only one instance per Telegram bot. If it detects an existing webhook, it stops without changing it: use a dedicated bot or explicitly adjust its configuration.

Generation requests are not automatically retried after a failure or interruption, to avoid an unintended additional paid call. Restarting during a request can interrupt the response. If a draft was already generated, retrieve it with `/last`; otherwise, resend your request. An incomplete OpenAI response is reported as a failure: check the model and output limit if this keeps happening.

Run the local tests without API keys or network access:

```sh
python3 -m unittest discover -s tests -v
```

## Add your tweet history

### 1. Download your archive from X

In a browser, sign in to the account whose writing style you want to use, then:

1. Open **More → Settings and privacy → Your account**.
2. Select **Download an archive of your data**.
3. Confirm your password, then verify your identity using the code sent by email or SMS.
4. Click **Request archive** or **Request data**, depending on the interface.
5. Wait for the email or notification from X; preparing the archive can take several days.
6. Return to this section and download the **ZIP** while signed in to the same account.

Your email address must be confirmed before requesting the archive. Labels may vary between the website and app; consult the [official X instructions](https://help.x.com/en/managing-your-account/how-to-download-your-x-archive) if they differ.

Keep the ZIP locally, outside the public repository: the full archive also contains private messages and account information. Tweetos reads only the tweet data needed for import; you do not need to extract the ZIP.

### 2. Provide the ZIP on your computer

The Tweetos repository must be on this computer. Keep the original archive in Downloads or another private folder outside the repository. The examples below prepare files in `references/`, where the personal output files are ignored by Git.

**With Codex or Claude Code**, open the Tweetos folder and provide the actual ZIP path and your account:

> Use Tweetos. My account is @my_username. Import my archive at C:\Users\Alice\Downloads\twitter-archive.zip into references/ with --account my_username. Verify the account before importing. Then analyze the tweets to create references/style.md, with dated examples and the dataset's limitations. Keep all three personal files out of Git.

Replace the example path with your own. The assistant needs access to your computer's files: sending this path to the Telegram bot does not give it access to your disk.

**With the import command**, Python 3.9 or newer must be available. From the repository folder in Windows PowerShell:

```powershell
python scripts/archive_tweets.py import --archive "C:\Users\Alice\Downloads\twitter-archive.zip" --account my_username --output references
```

On Linux or macOS:

```sh
python3 scripts/archive_tweets.py import --archive "/home/alice/Downloads/twitter-archive.zip" --account my_username --output references
```

Replace `my_username` with your X username without `@`. The import creates:

```text
references/
  tweets.jsonl          Tweet text and useful metadata
  corpus-summary.json   Account, date range, size, and import limitations
```

`--account` specifies the expected account. For a ZIP, the import checks `data/account.js` and rejects a different account before writing any files. For a standalone `tweets.js`, the account is declared by you and cannot be verified from that file; prefer the ZIP. The summary records the account and whether it was verified. The bot rejects a dataset whose declared account differs from `TWEETOS_X_ACCOUNT`. Older datasets without an account in their summary remain usable: verify their origin before selecting them.

The importer accepts an X ZIP archive containing `data/tweets.js` and any additional parts, or a standalone `tweets.js` file. It reads data without executing JavaScript. It excludes retweets and does not read private messages, the likes dataset, or deleted tweets. Long posts in the separate `note-tweet` dataset and community tweets are not imported.

### 3. Create your style profile

If you only ran the import command, ask Codex or Claude Code in the same folder:

> My account is @my_username. Analyze references/tweets.jsonl and references/corpus-summary.json, then create references/style.md with observed writing habits, dated examples, and the analysis limitations. Use this profile and the editorial guidelines to rewrite my next ideas without inventing facts.

The import script **does not create `style.md` automatically**. This step is complete when all three files exist:

```text
references/tweets.jsonl
references/corpus-summary.json
references/style.md
```

If you only use the skill with Codex or Claude Code, you can stop here and start giving it your ideas. For the Telegram bot in Docker, continue below.

### 4. Make the files available to Docker

`TWEETOS_HISTORY_DIR` points to a **folder on the Docker host** containing the three prepared files. Docker mounts it inside the container as read-only. The simplest setup is to import your history and run Docker on the same computer; no network transfer is needed.

From the repository folder, temporarily stop the bot so you can replace all three files together:

```sh
docker compose stop tweetos
```

For a first installation, there is no existing container to stop.

**On the same computer, with Windows / PowerShell:**

```powershell
New-Item -ItemType Directory -Force data/references | Out-Null
Copy-Item references/tweets.jsonl,references/corpus-summary.json,references/style.md -Destination data/references/
```

**On the same computer, with macOS:**

```sh
mkdir -p data/references
cp references/tweets.jsonl references/corpus-summary.json references/style.md data/references/
```

**On the same computer, with Linux and a standard Docker Engine installation:** these commands copy the files and set the permissions expected by the container:

```sh
sudo install -d -m 700 -o 10001 -g 10001 data data/references
sudo install -m 600 -o 10001 -g 10001 references/tweets.jsonl references/corpus-summary.json references/style.md data/references/
```

On a NAS, copy the three files into a private shared folder, then select that folder for the container's mount. For a remote server, use your usual transfer tool; an SSH example is provided below.

In `.env`, set the same account used for the import and the destination folder:

```ini
TWEETOS_X_ACCOUNT=my_username
TWEETOS_HISTORY_DIR=./data/references
```

The path is relative to `compose.yaml`, or absolute on the Docker host. If you choose another folder, adjust the copy destination and make sure the container can read it. Keep the original ZIP in a private location: the container only needs the three prepared files.

Validate and restart the bot from the repository folder:

```sh
docker compose run --rm tweetos --check
docker compose up -d --force-recreate
```

<details>
<summary>Optional: transfer files to a remote Docker host with SSH</summary>

This transfer is only needed when deploying on another machine accessible over SSH. Replace `user@DOCKER_HOST` with your SSH destination. On your computer, from the repository containing the imported files:

```sh
ssh user@DOCKER_HOST "umask 077; mkdir -p ~/tweetos-import; chmod 700 ~/tweetos-import"
scp references/tweets.jsonl references/corpus-summary.json references/style.md user@DOCKER_HOST:tweetos-import/
ssh user@DOCKER_HOST
```

On the remote machine, enter its repository folder, adjusting the path, then install the files. This example assumes a Linux host with a standard Docker Engine installation:

```sh
cd /path/to/tweetos
sudo docker compose stop tweetos
sudo install -d -m 700 -o 10001 -g 10001 data data/references
sudo install -m 600 -o 10001 -g 10001 ~/tweetos-import/tweets.jsonl ~/tweetos-import/corpus-summary.json ~/tweetos-import/style.md data/references/
sudo nano .env
```

Set `TWEETOS_X_ACCOUNT` and `TWEETOS_HISTORY_DIR` as described above, then run:

```sh
sudo docker compose run --rm tweetos --check
sudo docker compose up -d --force-recreate
```

After successfully copying the files, remove the staging copies:

```sh
rm -- ~/tweetos-import/tweets.jsonl ~/tweetos-import/corpus-summary.json ~/tweetos-import/style.md
rmdir -- ~/tweetos-import
```

</details>

### 5. Check the result in Telegram

Send `/status` to the bot. Its built-in status messages currently use French. Translated into English, a successfully loaded profile reports:

```text
Tweetos is active.
X account: @my_username.
Style profile: loaded.
History: loaded.
```

This means the bot is active and both the style profile and tweet history are loaded. You can now send an idea, for example: "Today I shipped keyword search. Rewrite that in my style."

`/status` confirms that the files exist; it does not guarantee their quality or that the entire X archive was imported. If a file is missing, check the configured folder, file copies, and permissions. If the account does not match, correct the dataset or `TWEETOS_X_ACCOUNT` before restarting.

To replace your history later, repeat steps 2 through 5, including recreating `style.md`. Do not publish these files on GitHub. With an assistant that has browser access, you can also build a sample of public tweets: preserve their links and dates, and describe the sample's coverage in the profile. The Telegram bot does not collect these tweets automatically.

## Example request

> Use Tweetos. Today I finished keyword search in my app. It works locally, but I don't have user feedback yet. Write a straightforward tweet about this progress.

Facts come from your brief. The skill does not invent customers, revenue, or results, and does not publish automatically.

## Repository contents

- `SKILL.md`: writing and style analysis instructions.
- `references/guidelines.md`: editable build in public editorial guidelines.
- `scripts/archive_tweets.py`: local archive import and example search.
- `dist/tweetos.zip`: skill package for Claude, without personal history.
- `scripts/telegram_bot.py`: Telegram bot using the OpenAI API.
- `deploy/`: configuration example and optional Linux systemd service.
- `Dockerfile`, `compose.yaml`, `.dockerignore`: Docker Compose deployment and a build context restricted to application files.
