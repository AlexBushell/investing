param(
    [string]$Project,
    [string]$Region,
    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$Service,

    [Parameter(Mandatory = $true)]
    [string]$SearxngSecret,

    [string]$InvokerMember,
    [string]$BaseUrl,
    [string]$ImageName = "searxng",
    [string]$Tag = "latest",
    [switch]$CreateRepository
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found on PATH: $Name"
    }
}

function Get-GcloudConfigValue {
    param([string]$Key)

    $value = gcloud config get-value $Key 2>$null
    if (-not $?) {
        return $null
    }
    $trimmed = $value.Trim()
    if (-not $trimmed -or $trimmed -eq "(unset)") {
        return $null
    }
    return $trimmed
}

Require-Command "gcloud"
Require-Command "docker"

if (-not $Project) {
    $Project = Get-GcloudConfigValue "project"
}
if (-not $Region) {
    $Region = Get-GcloudConfigValue "run/region"
}
if (-not $Project) {
    throw "Project not provided and no active gcloud default is set. Pass -Project or run 'gcloud config set project ...'."
}
if (-not $Region) {
    throw "Region not provided and no active gcloud default is set. Pass -Region or run 'gcloud config set run/region ...'."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$registryHost = "$Region-docker.pkg.dev"
$imageUri = "$registryHost/$Project/$Repository/$ImageName:$Tag"

Write-Host "Configuring Docker authentication for Artifact Registry host $registryHost..."
gcloud auth configure-docker $registryHost --quiet | Out-Null

if ($CreateRepository) {
    Write-Host "Ensuring Artifact Registry repository exists: $Repository"
    $repoExists = $true
    try {
        gcloud artifacts repositories describe $Repository `
            --location $Region `
            --project $Project | Out-Null
    }
    catch {
        $repoExists = $false
    }

    if (-not $repoExists) {
        gcloud artifacts repositories create $Repository `
            --repository-format docker `
            --location $Region `
            --project $Project `
            --description "SearXNG Cloud Run images"
    }
}

Write-Host "Building image: $imageUri"
docker build -t $imageUri $scriptDir

Write-Host "Pushing image: $imageUri"
docker push $imageUri

$envVars = @("SEARXNG_SECRET=$SearxngSecret")
if ($BaseUrl) {
    $envVars += "SEARXNG_BASE_URL=$BaseUrl"
}

Write-Host "Deploying Cloud Run service: $Service"
gcloud run deploy $Service `
    --image $imageUri `
    --project $Project `
    --region $Region `
    --platform managed `
    --port 8080 `
    --no-allow-unauthenticated `
    --set-env-vars ($envVars -join ",")

if ($InvokerMember) {
    Write-Host "Granting Cloud Run Invoker to: $InvokerMember"
    gcloud run services add-iam-policy-binding $Service `
        --project $Project `
        --region $Region `
        --member $InvokerMember `
        --role roles/run.invoker
}

Write-Host ""
Write-Host "Deployed image: $imageUri"
Write-Host "Cloud Run service: $Service"
Write-Host "Authentication: required"
if ($InvokerMember) {
    Write-Host "Explicit invoker member: $InvokerMember"
}
else {
    Write-Host "No explicit invoker member was granted by this script."
    Write-Host "Grant roles/run.invoker to your user if needed."
}
