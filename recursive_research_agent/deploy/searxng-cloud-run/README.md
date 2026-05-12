# SearXNG Cloud Run Bundle

This folder contains a minimal Cloud Run-oriented SearXNG image setup plus
helpers for pushing the image to Artifact Registry and deploying it privately.

## Files

- `Dockerfile`: builds from the official `searxng/searxng` image and overlays a custom `settings.yml`
- `settings.yml`: enables JSON responses and binds SearXNG to `0.0.0.0:8080`
- `deploy.ps1`: build, push, and deploy helper for PowerShell
- `deploy.sh`: build, push, and deploy helper for Bash

## Important

Do not bake a real secret into `settings.yml`.

Set the secret at deploy time with the `SEARXNG_SECRET` environment variable,
which overrides the file value.

## What The Deploy Helpers Do

The deploy scripts:

1. configure Docker auth for your Artifact Registry host
2. optionally create the Artifact Registry Docker repository
3. build the image from this folder
4. push it to Artifact Registry
5. deploy it to Cloud Run with `--no-allow-unauthenticated`
6. optionally grant `roles/run.invoker` to one explicit principal

If `Project` / `--project` or `Region` / `--region` are omitted, the scripts
fall back to the active `gcloud` defaults:

- `gcloud config get-value project`
- `gcloud config get-value run/region`

Set those once with:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region YOUR_REGION
```

## PowerShell Example

```powershell
.\deploy.ps1 `
  -Repository containers `
  -Service searxng `
  -SearxngSecret YOUR_RANDOM_SECRET `
  -InvokerMember user:you@example.com `
  -CreateRepository
```

## Bash Example

```bash
./deploy.sh \
  --repository containers \
  --service searxng \
  --searxng-secret YOUR_RANDOM_SECRET \
  --invoker-member user:you@example.com \
  --create-repository
```

If you want generated links to use the Cloud Run URL, also set `SEARXNG_BASE_URL`
using `-BaseUrl` or `--base-url`.

## Authentication Notes

`--no-allow-unauthenticated` makes the Cloud Run service require authentication.

If you want the service callable by just your user account, pass your own member
identity such as:

- `user:you@example.com`

The deploy script grants `roles/run.invoker` to that member when
`InvokerMember` / `--invoker-member` is supplied.

Note that project owners, editors, admins, or other principals with broader IAM
permissions may still be able to change the service or grant themselves access.
So "only I can access it" really means "only my chosen principal is granted
invoker access by this deployment."
