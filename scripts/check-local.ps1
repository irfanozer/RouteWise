[CmdletBinding()]
param(
    [string]$BaseUrl = "http://localhost:3003"
)

$ErrorActionPreference = "Stop"

Write-Host "Checking RouteWise web entry point..."
$web = Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing -TimeoutSec 15
if ($web.StatusCode -ne 200) {
    throw "Frontend health check returned HTTP $($web.StatusCode)."
}

Write-Host "Checking production browser security headers..."
$home = Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -TimeoutSec 15
$requiredHeaders = @{
    "Content-Security-Policy" = "default-src"
    "X-Content-Type-Options" = "nosniff"
    "X-Frame-Options" = "DENY"
}
foreach ($headerName in $requiredHeaders.Keys) {
    $headerValue = [string]$home.Headers[$headerName]
    if (-not $headerValue -or -not $headerValue.Contains($requiredHeaders[$headerName])) {
        throw "Frontend response is missing the expected $headerName security header."
    }
}

Write-Host "Checking RouteWise API and database..."
$ready = Invoke-RestMethod -Uri "$BaseUrl/health/ready" -TimeoutSec 15
if ($ready.status -ne "ready") {
    throw "Backend readiness did not return status=ready."
}

$network = Invoke-RestMethod -Uri "$BaseUrl/api/v1/network" -TimeoutSec 15
$scenarios = Invoke-RestMethod -Uri "$BaseUrl/api/v1/scenarios" -TimeoutSec 15
if (-not $network) {
    throw "The seeded network response was empty."
}
if (-not $scenarios) {
    throw "The disruption scenario response was empty."
}

Write-Host "Checking a stored and replayed routing decision..."
$requestBody = @{
    origin_id = "northgate"
    destination_id = "airport"
    objective = "fastest"
    scenario_id = "central-closure"
    constraints = @{
        wheelchair_required = $false
        max_transfers = $null
    }
} | ConvertTo-Json -Depth 4

$comparison = Invoke-RestMethod `
    -Uri "$BaseUrl/api/v1/routes/compare" `
    -Method Post `
    -ContentType "application/json" `
    -Body $requestBody `
    -TimeoutSec 30
if (-not $comparison.run_id -or -not $comparison.baseline -or -not $comparison.explanation) {
    throw "The route comparison did not include its receipt, baseline, and explanation."
}

$savedRun = Invoke-RestMethod `
    -Uri "$BaseUrl/api/v1/runs/$($comparison.run_id)" `
    -TimeoutSec 15
if ($savedRun.run_id -ne $comparison.run_id) {
    throw "The saved route receipt did not match the calculation response."
}

$replay = Invoke-RestMethod `
    -Uri "$BaseUrl/api/v1/runs/$($comparison.run_id)/replay" `
    -Method Post `
    -TimeoutSec 30
if ($replay.evidence.replayed_from_run_id -ne $comparison.run_id) {
    throw "The replay did not identify the original route receipt."
}
if (($replay.baseline.station_ids -join ",") -ne ($comparison.baseline.station_ids -join ",")) {
    throw "The replayed baseline route did not match the original route."
}
if (($replay.disrupted.station_ids -join ",") -ne ($comparison.disrupted.station_ids -join ",")) {
    throw "The replayed disrupted route did not match the original route."
}

Write-Host "RouteWise is ready at $BaseUrl" -ForegroundColor Green
