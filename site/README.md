# agentloss.com — discovery + install site

The canonical discovery and install home for **agentloss** (the loss layer for AI agent
traces). Static, fast, human- and agent-legible. Its most important job besides the
landing page: serve **`agentloss.com/llms.txt`**, the standard path coding agents fetch to
learn a tool.

## What's here

```
site/
├── index.html      # landing page (semantic HTML, OG/meta, JSON-LD, quickstart)
├── styles.css      # small hand-written stylesheet (no framework)
├── copy.js         # copy-to-clipboard for the install command + code blocks
├── favicon.svg     # site icon
├── og.svg          # Open Graph / Twitter card image
├── robots.txt      # allow all crawlers; references /sitemap.xml and /llms.txt
├── sitemap.xml     # minimal sitemap (/, /llms.txt)
├── build.sh        # assembles ./public and copies llms.txt FRESH from repo root
├── vercel.json     # Vercel static config (build command + /llms.txt headers)
├── package.json    # `npm run build` / `npm run preview` convenience
├── .gitignore      # ignores public/ (build output) and .vercel/
└── README.md       # this file
```

The built output goes to `site/public/` and is **not committed** (see `.gitignore`).

## Build

```bash
cd site
bash build.sh        # or: npm run build
```

`build.sh` copies the static assets into `public/` and, critically, copies
**`llms.txt` from the repo root** into `public/llms.txt` at build time. We never commit a
static copy of `llms.txt` — it is edited concurrently in the package repo, so the build
always picks up the current version. The script locates the repo root via
`git rev-parse --show-toplevel` (falling back to `..`), so it works both locally and in
Vercel's checkout.

### Verify locally

```bash
cd site
bash build.sh
test -f public/index.html && echo "index.html OK"
test -f public/llms.txt   && echo "llms.txt OK"

# preview in a browser:
npm run preview           # builds, then serves ./public at http://localhost:3000
```

## Deploy on Vercel

The team uses Vercel. The site is a plain static build; `vercel.json` wires it up.

**One-time project setup**

1. In the Vercel dashboard: **Add New… → Project**, import
   `github.com/ADMT-ai/agentloss`.
2. **Root Directory:** set to `site`. (This makes `build.sh` run from `site/`; it still
   reaches `../llms.txt` because Vercel checks out the whole repo.)
3. **Framework Preset:** Other. Build settings are read from `site/vercel.json`
   (`buildCommand: bash build.sh`, `outputDirectory: public`) — leave the dashboard
   fields on their defaults / empty.
4. Deploy.

**From the CLI** (from `site/`):

```bash
cd site
npx vercel        # preview deploy -> prints a *.vercel.app URL
npx vercel --prod # production deploy (owner action)
```

A preview deploy is safe for validation. **Production deploy and domain config are the
owner's action.**

### Point agentloss.com at it (DNS)

Do this in the Vercel dashboard after the first production deploy:

1. **Project → Settings → Domains → Add** `agentloss.com` (and `www.agentloss.com`).
2. Vercel shows the records to create at your DNS registrar/provider:
   - **Apex `agentloss.com`:** an **A record** to `76.76.21.21`
     *(or)* use Vercel nameservers / an `ALIAS`/`ANAME` to `cname.vercel-dns.com` if your
     provider supports apex flattening.
   - **`www.agentloss.com`:** a **CNAME** to `cname.vercel-dns.com`.
   - Recommended: set `www` (or apex) to redirect to the canonical host in
     **Settings → Domains**.
3. Wait for DNS propagation; Vercel auto-provisions the TLS certificate.
4. Verify:
   ```bash
   curl -sI https://agentloss.com/llms.txt      # 200, content-type: text/plain
   curl -s  https://agentloss.com/llms.txt | head
   curl -sI https://agentloss.com/               # 200, index.html
   ```

## Serving /llms.txt

`vercel.json` sets `Content-Type: text/plain; charset=utf-8` and permissive CORS on
`/llms.txt` so agents can fetch it cross-origin. Because it is copied at build time, every
deploy serves whatever `llms.txt` is at the repo root for that commit.
