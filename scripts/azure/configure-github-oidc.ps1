[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $SubscriptionId,

    [Parameter(Mandatory)]
    [string] $GitHubRepository,

    [string] $ResourceGroup = "rg-routewise-prod",
    [string] $GitHubEnvironment = "production",
    [string] $ApplicationName = "routewise-github-production"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Test-Path Variable:\PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $true
}

foreach ($command in @("az", "gh")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command '$command' is not installed or is not on PATH."
    }
}

gh auth status | Out-Null
$requestedParts = $GitHubRepository.Split('/', 2)
if ($requestedParts.Count -ne 2) {
    throw "-GitHubRepository must use OWNER/REPOSITORY format, for example irfanozer/RouteWise."
}

$repositoryMetadata = (gh api "repos/$GitHubRepository") | ConvertFrom-Json
$canonicalOwner = [string] $repositoryMetadata.owner.login
$canonicalRepository = [string] $repositoryMetadata.name
$ownerId = [string] $repositoryMetadata.owner.id
$repositoryId = [string] $repositoryMetadata.id
if (-not $canonicalOwner -or -not $canonicalRepository -or -not $ownerId -or -not $repositoryId) {
    throw "GitHub did not return the repository identifiers required for OIDC."
}
$repository = "$canonicalOwner/$canonicalRepository"

gh api --method PUT "repos/$repository/environments/$GitHubEnvironment" | Out-Null

az account set --subscription $SubscriptionId
$account = az account show --output json | ConvertFrom-Json
$tenantId = [string] $account.tenantId
if (-not $tenantId) {
    throw "Azure CLI is not signed in. Run 'az login' and try again."
}

$resourceGroupId = az group show --name $ResourceGroup --query id --output tsv --only-show-errors
if (-not $resourceGroupId) {
    throw "Resource group '$ResourceGroup' does not exist. Run bootstrap-foundation.ps1 first."
}

$clientId = az ad app list --display-name $ApplicationName --query "[0].appId" --output tsv --only-show-errors
if (-not $clientId) {
    $clientId = az ad app create --display-name $ApplicationName --query appId --output tsv --only-show-errors
}
$applicationObjectId = az ad app show --id $clientId --query id --output tsv --only-show-errors
$servicePrincipalId = az ad sp list --filter "appId eq '$clientId'" --query "[0].id" --output tsv --only-show-errors
if (-not $servicePrincipalId) {
    $servicePrincipalId = az ad sp create --id $clientId --query id --output tsv --only-show-errors
}

$credentialName = "github-$($GitHubEnvironment -replace '[^A-Za-z0-9-]', '-')"
$subject = "repo:${canonicalOwner}@${ownerId}/${canonicalRepository}@${repositoryId}:environment:${GitHubEnvironment}"
$existingJson = az ad app federated-credential list --id $applicationObjectId --query "[?name=='$credentialName'] | [0]" --output json --only-show-errors
$existing = if ($existingJson -and $existingJson -ne "null") { $existingJson | ConvertFrom-Json } else { $null }

if (-not $existing -or [string] $existing.subject -ne $subject) {
    $credentialFile = Join-Path ([System.IO.Path]::GetTempPath()) "routewise-oidc-$([Guid]::NewGuid().ToString('N')).json"
    try {
        $credential = @{
            issuer = "https://token.actions.githubusercontent.com"
            subject = $subject
            audiences = @("api://AzureADTokenExchange")
            description = "RouteWise production deployments from GitHub Actions"
        }
        if (-not $existing) { $credential.name = $credentialName }
        [System.IO.File]::WriteAllText(
            $credentialFile,
            ($credential | ConvertTo-Json -Depth 4),
            [System.Text.UTF8Encoding]::new($false)
        )
        if ($existing) {
            az ad app federated-credential update --id $applicationObjectId --federated-credential-id $credentialName --parameters "@$credentialFile" --only-show-errors --output none
        }
        else {
            az ad app federated-credential create --id $applicationObjectId --parameters "@$credentialFile" --only-show-errors --output none
        }
    }
    finally {
        if ([System.IO.File]::Exists($credentialFile)) { [System.IO.File]::Delete($credentialFile) }
    }
}

$roleAssignment = az role assignment list --assignee-object-id $servicePrincipalId --scope $resourceGroupId --role Contributor --query "[0].id" --output tsv --only-show-errors
if (-not $roleAssignment) {
    az role assignment create --assignee-object-id $servicePrincipalId --assignee-principal-type ServicePrincipal --role Contributor --scope $resourceGroupId --only-show-errors --output none
}

gh variable set AZURE_CLIENT_ID --repo $repository --body $clientId
gh variable set AZURE_TENANT_ID --repo $repository --body $tenantId
gh variable set AZURE_SUBSCRIPTION_ID --repo $repository --body $SubscriptionId

Write-Host "GitHub OIDC is ready. No Azure client secret was created." -ForegroundColor Green
Write-Host "Federated subject: $subject"
