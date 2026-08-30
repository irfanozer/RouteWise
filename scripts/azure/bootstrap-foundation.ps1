[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $SubscriptionId,

    [Parameter(Mandatory)]
    [string] $GitHubRepository,

    [string] $Location = "eastus2",
    [string] $ResourceGroup = "rg-routewise-prod",
    [string] $NamePrefix = "routewise",
    [string] $EnvironmentName = "prod",
    [string] $CustomDomain = "routewise.irfanburakozer.com",
    [string] $PostgresAdministratorLogin = "routewise_admin",
    [string] $PostgresDatabaseName = "routewise",
    [SecureString] $PostgresAdministratorPassword,

    [Parameter(Mandatory)]
    [switch] $ConfirmCosts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Test-Path Variable:\PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $true
}

function Assert-Command {
    param([Parameter(Mandatory)][string] $Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not installed or is not on PATH."
    }
}

function New-DatabasePassword {
    $randomBytes = New-Object byte[] 30
    $randomNumberSource = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomNumberSource.GetBytes($randomBytes)
    }
    finally {
        $randomNumberSource.Dispose()
    }
    $randomText = [Convert]::ToBase64String($randomBytes).TrimEnd("=").Replace("+", "A").Replace("/", "b")
    return "Rw9!$randomText"
}

if (-not $ConfirmCosts) {
    throw "Review docs/DEPLOYMENT.md, then pass -ConfirmCosts to create billable Azure resources."
}

Assert-Command -Name "az"
Assert-Command -Name "gh"
gh auth status | Out-Null

$repositoryParts = $GitHubRepository.Split('/', 2)
if ($repositoryParts.Count -ne 2 -or [string]::IsNullOrWhiteSpace($repositoryParts[0]) -or [string]::IsNullOrWhiteSpace($repositoryParts[1])) {
    throw "-GitHubRepository must use OWNER/REPOSITORY format, for example irfanozer/route-wise."
}
$repositoryMetadataJson = gh api "repos/$GitHubRepository"
if ($LASTEXITCODE -ne 0 -or -not $repositoryMetadataJson) {
    throw "GitHub repository '$GitHubRepository' could not be read."
}
$repositoryMetadata = $repositoryMetadataJson | ConvertFrom-Json
$canonicalOwner = [string] $repositoryMetadata.owner.login
$canonicalRepository = [string] $repositoryMetadata.name
if (-not $canonicalOwner -or -not $canonicalRepository) {
    throw "GitHub did not return the canonical repository name."
}
$repository = "$canonicalOwner/$canonicalRepository"

az account set --subscription $SubscriptionId
$account = az account show --output json | ConvertFrom-Json
if (-not $account.id) {
    throw "Azure CLI is not signed in. Run 'az login' and try again."
}

foreach ($provider in @("Microsoft.App", "Microsoft.DBforPostgreSQL", "Microsoft.Network", "Microsoft.OperationalInsights")) {
    Write-Host "Registering Azure provider $provider ..."
    az provider register --namespace $provider --wait --only-show-errors | Out-Null
}

Write-Host "Creating resource group $ResourceGroup in $Location ..."
az group create `
    --name $ResourceGroup `
    --location $Location `
    --tags project=routewise environment=production managed-by=bicep `
    --only-show-errors `
    --output none

$plainPassword = if ($PostgresAdministratorPassword) {
    ([System.Net.NetworkCredential]::new("", $PostgresAdministratorPassword)).Password
}
else {
    New-DatabasePassword
}

$parameterFile = Join-Path ([System.IO.Path]::GetTempPath()) "routewise-$([Guid]::NewGuid().ToString('N')).parameters.json"
try {
    $parameters = @{
        '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
        contentVersion = "1.0.0.0"
        parameters = @{
            location = @{ value = $Location }
            namePrefix = @{ value = $NamePrefix }
            environmentName = @{ value = $EnvironmentName }
            postgresAdministratorLogin = @{ value = $PostgresAdministratorLogin }
            postgresAdministratorPassword = @{ value = $plainPassword }
            postgresDatabaseName = @{ value = $PostgresDatabaseName }
        }
    }
    [System.IO.File]::WriteAllText(
        $parameterFile,
        ($parameters | ConvertTo-Json -Depth 8),
        [System.Text.UTF8Encoding]::new($false)
    )

    az deployment group validate `
        --resource-group $ResourceGroup `
        --template-file "infra/azure/foundation.bicep" `
        --parameters "@$parameterFile" `
        --only-show-errors `
        --output none

    $outputs = az deployment group create `
        --resource-group $ResourceGroup `
        --name "foundation-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))" `
        --template-file "infra/azure/foundation.bicep" `
        --parameters "@$parameterFile" `
        --only-show-errors `
        --query properties.outputs `
        --output json | ConvertFrom-Json
}
finally {
    if ([System.IO.File]::Exists($parameterFile)) {
        [System.IO.File]::Delete($parameterFile)
    }
}

$encodedUser = [Uri]::EscapeDataString($PostgresAdministratorLogin)
$encodedPassword = [Uri]::EscapeDataString($plainPassword)
$databaseUrl = "postgresql+asyncpg://${encodedUser}:${encodedPassword}@$($outputs.postgresServerFqdn.value):5432/$($outputs.postgresDatabaseName.value)?ssl=require"

$databaseUrl | gh secret set ROUTEWISE_DATABASE_URL --repo $repository
gh variable set AZURE_RESOURCE_GROUP --repo $repository --body $ResourceGroup
gh variable set AZURE_NAME_PREFIX --repo $repository --body $NamePrefix
gh variable set AZURE_ENVIRONMENT_NAME --repo $repository --body $EnvironmentName
gh variable set AZURE_CONTAINER_APPS_ENVIRONMENT --repo $repository --body $outputs.containerAppsEnvironmentName.value
gh variable set ROUTEWISE_CUSTOM_DOMAIN --repo $repository --body $CustomDomain
gh variable set ROUTEWISE_REQUIRE_CUSTOM_DOMAIN --repo $repository --body "false"
gh variable set ROUTEWISE_GHCR_PULL_USERNAME --repo $repository --body $canonicalOwner
gh variable set AZURE_DEPLOYMENT_ENABLED --repo $repository --body "false"

$plainPassword = $null
$databaseUrl = $null

Write-Host "Foundation created. Deployment remains disabled." -ForegroundColor Green
Write-Host "Next: run scripts/azure/configure-github-oidc.ps1."
