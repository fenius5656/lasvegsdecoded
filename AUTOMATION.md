# Auto-Blog Automation — Setup Guide

This makes new **long-form** videos turn into rich, brand-styled blog posts automatically:

1. A daily GitHub Action finds long-form videos that don't have a post yet.
2. It locates the **matching episode script in your Google Drive** and reads its verified facts.
3. It calls the **Claude API** to write a ~1,000–1,400 word post (TL;DR box, sections, tip, verdict, FAQ).
4. It opens a **Pull Request** with the draft. **You review and click "Merge" to publish.**

> Why a PR instead of auto-publishing? It's a ~15-second safety check so a wrong fact never
> hits the live site unattended. Once you trust it, you can flip to fully-auto (see the end).

**Cost:** a few cents per post via the Claude API. Everything else is free.

---

## What you need to set up (one time, ~20 minutes)

You'll create **two secrets** and (optionally) **two variables** in the GitHub repo.

### 1. Anthropic (Claude) API key

1. Go to <https://console.anthropic.com> → sign in → **API Keys** → **Create Key**.
2. Add a small amount of credit (Billing) — posts cost pennies, so a few dollars lasts a long time.
3. Copy the key (starts with `sk-ant-...`).
4. In your repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `ANTHROPIC_API_KEY`
   - Value: paste the key

### 2. Google service account (so the Action can read your Drive scripts)

A service account is a "robot" Google account the Action logs in as.

1. Go to <https://console.cloud.google.com> → create a project (any name, e.g. "vegas-decoded").
2. **APIs & Services → Library** → search **Google Drive API** → **Enable**.
3. **APIs & Services → Credentials → Create Credentials → Service account**.
   - Give it a name (e.g. "blog-bot") → **Create and continue** → **Done**.
4. Click the new service account → **Keys → Add key → Create new key → JSON** → download the file.
5. Open that JSON file, copy its **entire contents**.
6. In your repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GDRIVE_SA_KEY`
   - Value: paste the whole JSON
7. **Share your scripts with the robot:** in the JSON you'll see a `"client_email"` like
   `blog-bot@vegas-decoded.iam.gserviceaccount.com`. In Google Drive, find the folder that holds
   your Vegas Decoded episode scripts, right-click → **Share** → paste that email → **Viewer** → send.
   (Sharing the top folder covers everything inside it.)

### 3. (Recommended) Point it at your scripts folder — a Variable, not a secret

This narrows the search so it only looks in your scripts folder.

1. Open your scripts folder in Google Drive. The URL looks like
   `https://drive.google.com/drive/folders/1AbCdEf...` — copy the part after `/folders/`.
2. In your repo: **Settings → Secrets and variables → Actions → Variables → New repository variable**
   - Name: `GDRIVE_FOLDER_ID`
   - Value: paste the folder ID

### 4. (Optional) Cheaper model + volume — Variables

- `VD_MODEL` = `claude-sonnet-5` → roughly half the per-post cost (default is `claude-opus-5`).
- `VD_MAX_POSTS` = `2` → how many posts to draft per run (default 2).

### 5. Let Actions open Pull Requests

**Settings → Actions → General → Workflow permissions** → ensure
**"Allow GitHub Actions to create and approve pull requests"** is checked → Save.

---

## Using it

- It runs **daily** on its own. To try it now: **Actions tab → "Auto-generate blog posts" → Run workflow**.
- When it drafts posts, a **Pull Request** appears (Pull requests tab). Open it, skim the post(s),
  and click **Merge** to publish — GitHub Pages redeploys automatically. If a post looks wrong,
  just **Close** the PR (nothing publishes) or edit the files on that branch first.

### First run — watch it once
The very first run proves the two connections work (Drive + Claude). If it makes no PR:
- Open the run logs (**Actions** tab → the run → the "Generate posts" step).
- "No matching Drive script found" → make sure the scripts folder is shared with the service-account
  email and `GDRIVE_FOLDER_ID` is set.
- An auth error on Claude → check the `ANTHROPIC_API_KEY` secret and that the account has credit.

---

## Going fully auto (later, optional)

Once you trust the quality, you can skip the PR step and commit posts straight to `main`:
tell me and I'll switch the workflow to commit directly instead of opening a PR. Until then,
the one-click merge is your safety net.

## What it will NOT touch
- Shorts (only long-form episodes become posts).
- Videos that already have a post (tracked by `videoId` in `data/posts.json`).
- Anything already published — it only ever adds new draft files in a PR.
