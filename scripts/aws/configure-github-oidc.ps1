[CmdletBinding()]
param(
    [string] $GitHubRepository = "irfanozer/RouteWise",
    [string] $Region = "us-east-1",
    [string] $Profile = "routewise",
    [string] $StackName = "routewise-aws-prod",
    [switch] $EnableDeployment
)
. "$PSScriptRoot/common.ps1"
Initialize-RouteWiseAws -Region $Region -Profile $Profile
$stack = Get-RouteWiseStack $StackName
if (-not $stack) { throw "Run the AWS foundation bootstrap first." }
$outputs = Get-RouteWiseOutputs $stack
$origin = $outputs.OriginDomainName
if ($EnableDeployment) {
    $addresses = [Net.Dns]::GetHostAddresses($origin) | ForEach-Object IPAddressToString
    if ($outputs.PublicIp -notin $addresses) { throw "$origin must resolve directly to $($outputs.PublicIp) before enabling deployment. Set its A record to DNS only." }
}
$repositoryJson = gh api "repos/$GitHubRepository"
if ($LASTEXITCODE -ne 0) { throw "Run gh auth login and verify the repository name." }
$repository = ($repositoryJson | ConvertFrom-Json).full_name
$configuredRepository = ($stack.Parameters | Where-Object ParameterKey -eq "GitHubRepository").ParameterValue
if ($repository -cne $configuredRepository) { throw "Repository does not match the stack's exact GitHubRepository: $configuredRepository" }
$PSNativeCommandUseErrorActionPreference = $false
$environmentJson = gh api "repos/$repository/environments/aws-production" 2>&1
if ($LASTEXITCODE -ne 0) {
    if (($environmentJson -join "`n") -notmatch "HTTP 404") { throw "Cannot inspect the GitHub environment: $environmentJson" }
    $environmentBody = '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}'
    $environmentBody | gh api --method PUT "repos/$repository/environments/aws-production" --input - | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot create the aws-production GitHub environment." }
    gh api --method POST "repos/$repository/environments/aws-production/deployment-branch-policies" -f name=main -f type=branch | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot restrict AWS deployments to main." }
}
else {
    $environment = ($environmentJson -join "`n") | ConvertFrom-Json
    if (-not $environment.deployment_branch_policy) {
        throw "In GitHub Settings > Environments > aws-production, restrict deployment branches to main. Existing environment protections are not overwritten."
    }
    if (-not $environment.deployment_branch_policy.custom_branch_policies) {
        throw "Set aws-production deployment branches to Selected branches and tags, allowing only the main branch."
    }
    $rulesJson = gh api "repos/$repository/environments/aws-production/deployment-branch-policies"
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect environment branch rules." }
    $rules = @(($rulesJson | ConvertFrom-Json).branch_policies)
    if ($rules.Count -ne 1 -or $rules[0].name -ne "main" -or $rules[0].type -ne "branch") {
        throw "The aws-production environment must allow only the main branch. Existing rules were preserved."
    }
}
$variables = @{
    AWS_REGION = $Region
    AWS_STACK_NAME = $StackName
    AWS_DEPLOYMENT_ROLE_ARN = $outputs.DeploymentRoleArn
}
if ($EnableDeployment) { $variables.AWS_DEPLOYMENT_ENABLED = "true" }
foreach ($key in $variables.Keys) {
    gh variable set $key --repo $repository --body $variables[$key]
    if ($LASTEXITCODE -ne 0) { throw "Failed to set GitHub variable $key." }
}
Write-Host "AWS deployment settings are ready. No permanent AWS access keys are stored in GitHub."
Write-Host "Azure files, variables, credentials, and deployment settings were not changed."
Write-Host "Run GitHub Actions > Deploy RouteWise to AWS > Run workflow on main."
