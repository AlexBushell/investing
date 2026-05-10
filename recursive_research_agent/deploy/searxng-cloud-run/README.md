# SearXNG Cloud Run Bundle

This folder contains a minimal Cloud Run-oriented SearXNG image setup.

## Files

- `Dockerfile`: builds from the official `searxng/searxng` image and overlays a custom `settings.yml`
- `settings.yml`: enables JSON responses and binds SearXNG to `0.0.0.0:8080`

## Important

Do not bake a real secret into `settings.yml`.

Set the secret at deploy time with the `SEARXNG_SECRET` environment variable, which overrides the file value.

Example:

```bash
gcloud run deploy searxng \
  --source . \
  --region YOUR_REGION \
  --no-allow-unauthenticated \
  --set-env-vars SEARXNG_SECRET=YOUR_RANDOM_SECRET
```

If you want generated links to use the Cloud Run URL, also set `SEARXNG_BASE_URL`.
