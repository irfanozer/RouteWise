[CmdletBinding()]
param(
    [string] $GitHubRepository = "irfanozer/RouteWise",
    [string] $Region = "us-east-1",
    [string] $Profile = "routewise",
    [string] $StackName = "routewise-aws-prod",
    [string] $OriginDomain = "origin-routewise.irfanburakozer.com",
    [ValidateSet("t3.small", "t3.medium")][string] $InstanceType = "t3.small",
    [Parameter(Mandatory)][switch] $ConfirmCosts
)
$explicitArguments = @{} + $PSBoundParameters
. "$PSScriptRoot/common.ps1"
if (-not $ConfirmCosts) { throw "Read docs/AWS_DEPLOYMENT.md and pass -ConfirmCosts before creating billable resources." }
Assert-RouteWiseDomain $OriginDomain
Initialize-RouteWiseAws -Region $Region -Profile $Profile
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "Install GitHub CLI and run gh auth login first." }
$repositoryJson = gh api "repos/$GitHubRepository"
if ($LASTEXITCODE -ne 0) { throw "Cannot read the GitHub repository. Check gh auth status." }
$repository = $repositoryJson | ConvertFrom-Json
$account = Invoke-RouteWiseAws -Arguments @("sts", "get-caller-identity")
Write-Host "AWS account: $($account.Account). Region: $Region. Stack: $StackName. Instance: $InstanceType."
Write-Host "This creates a continuously running server, disks, public IPv4, S3, and CloudFront. Credits are temporary."

$previous = Get-RouteWiseStack $StackName
if ($previous -and $previous.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE")) {
    throw "Stack status is $($previous.StackStatus). Resolve the existing operation in CloudFormation before continuing."
}
$providerArn = "arn:aws:iam::$($account.Account):oidc-provider/token.actions.githubusercontent.com"
$provider = Invoke-RouteWiseAws -Arguments @("iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", $providerArn) -MissingPattern "NoSuchEntity"
if ($provider -and "sts.amazonaws.com" -notin $provider.ClientIDList) {
    throw "The existing GitHub OIDC provider lacks the sts.amazonaws.com audience. Review it in IAM without removing other audiences."
}
# Preserve provider ownership on updates: never switch a stack-created provider
# to an external reference, which could cause CloudFormation to remove it.
$existingProviderArn = if ($provider) { $providerArn } else { "" }
if ($previous) {
    $existingProviderArn = ($previous.Parameters | Where-Object ParameterKey -eq "ExistingGitHubOidcProviderArn").ParameterValue
}

$secrets = @{}
foreach ($name in @("database-password", "origin-token")) {
    $path = "/routewise/prod/$name"
    $secret = Invoke-RouteWiseAws -Arguments @("ssm", "get-parameter", "--name", $path, "--with-decryption") -MissingPattern "ParameterNotFound"
    if ($null -eq $secret) {
        if ($previous) { throw "Existing deployment is missing $path. Recover its original value; do not generate a new database password." }
        $bytes = New-Object byte[] 32
        $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
        $value = ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
        Invoke-RouteWiseAwsJson -Arguments @("ssm", "put-parameter") -Payload @{
            Name = $path; Type = "SecureString"; Tier = "Standard"; Value = $value
            Description = "RouteWise AWS production $name. Preserve when updating the stack."
        } | Out-Null
    }
    else {
        if ($secret.Parameter.Type -ne "SecureString") { throw "$path must be a SecureString. Review the existing parameter without printing its value." }
        $value = $secret.Parameter.Value
    }
    if ($value -notmatch '^[a-f0-9]{64}$') { throw "Unexpected format in $path. This bootstrap requires a 64-character hexadecimal secret." }
    $secrets[$name] = $value
}
$prefixLists = Invoke-RouteWiseAws -Arguments @("ec2", "describe-managed-prefix-lists", "--filters", "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing")
if (@($prefixLists.PrefixLists).Count -ne 1) { throw "Could not identify the AWS-managed CloudFront origin prefix list." }
$values = [ordered]@{
    GitHubRepository = $repository.full_name
    GitHubOwnerId = [string] $repository.owner.id
    GitHubRepositoryId = [string] $repository.id
    ExistingGitHubOidcProviderArn = $existingProviderArn
    EnvironmentName = "aws-production"
    OriginDomain = $OriginDomain
    InstanceType = $InstanceType
    OriginVerifyToken = $secrets["origin-token"]
    CloudFrontPrefixListId = $prefixLists.PrefixLists[0].PrefixListId
}
$parameters = @($values.GetEnumerator() | ForEach-Object {
    if ($previous -and $_.Key -in @("OriginDomain", "InstanceType") -and -not $explicitArguments.ContainsKey($_.Key)) {
        @{ ParameterKey = $_.Key; UsePreviousValue = $true }
    }
    else { @{ ParameterKey = $_.Key; ParameterValue = [string] $_.Value } }
})
if ($previous) { $parameters += @{ ParameterKey = "BackupRetentionDays"; UsePreviousValue = $true } }
if ($previous) { $parameters += @{ ParameterKey = "AmiId"; UsePreviousValue = $true } }
else {
    $ami = Invoke-RouteWiseAws -Arguments @("ssm", "get-parameter", "--name", "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64")
    $parameters += @{ ParameterKey = "AmiId"; ParameterValue = $ami.Parameter.Value }
}
foreach ($key in @("WebCustomDomain", "WebCertificateArn")) {
    if ($previous) { $parameters += @{ ParameterKey = $key; UsePreviousValue = $true } }
    else { $parameters += @{ ParameterKey = $key; ParameterValue = "" } }
}
$template = [IO.File]::ReadAllText((Join-Path $PSScriptRoot "../../infra/aws/foundation.yaml"))
$payload = @{
    StackName = $StackName; TemplateBody = $template; Parameters = $parameters
    Capabilities = @("CAPABILITY_NAMED_IAM")
    Tags = @(@{ Key = "Project"; Value = "RouteWise" }, @{ Key = "Environment"; Value = "production" })
}
if ($previous) {
    $updated = Invoke-RouteWiseAwsJson -Arguments @("cloudformation", "update-stack") -Payload $payload -MissingPattern "No updates are to be performed"
    if ($updated) { Wait-RouteWiseStack -StackName $StackName -Creating $false }
}
else {
    $payload.EnableTerminationProtection = $true
    Invoke-RouteWiseAwsJson -Arguments @("cloudformation", "create-stack") -Payload $payload | Out-Null
    Wait-RouteWiseStack -StackName $StackName -Creating $true
}
$outputs = Get-RouteWiseOutputs (Get-RouteWiseStack $StackName)
Write-Host "`nCreate this ADDITIONAL Cloudflare DNS record (DNS only, gray cloud):"
Write-Host "A     $OriginDomain     $($outputs.PublicIp)"
Write-Host "Do not change routewise.irfanburakozer.com yet. Azure stays live."
Write-Host "AWS preview after the first deployment: https://$($outputs.DistributionDomainName)"
Write-Host "Next: scripts/aws/configure-github-oidc.ps1 -Profile $Profile -EnableDeployment"
