[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $CertificateArn,
    [string] $Domain = "routewise.irfanburakozer.com",
    [string] $Region = "us-east-1",
    [string] $Profile = "routewise",
    [string] $StackName = "routewise-aws-prod"
)
. "$PSScriptRoot/common.ps1"
Assert-RouteWiseDomain $Domain
Initialize-RouteWiseAws -Region $Region -Profile $Profile
$account = Invoke-RouteWiseAws -Arguments @("sts", "get-caller-identity")
if ($CertificateArn -notmatch "^arn:aws:acm:us-east-1:$($account.Account):certificate/[a-f0-9-]+$") {
    throw "Supply a certificate from this AWS account in us-east-1."
}
$certificate = (Invoke-RouteWiseAws -Arguments @("acm", "describe-certificate", "--certificate-arn", $CertificateArn)).Certificate
if ($certificate.Status -ne "ISSUED" -or $Domain -notin $certificate.SubjectAlternativeNames) {
    throw "The certificate must be ISSUED and explicitly cover $Domain. Add ACM's validation CNAME in Cloudflare first."
}
$stack = Get-RouteWiseStack $StackName
if (-not $stack -or $stack.StackStatus -notin @("CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE")) {
    throw "The AWS foundation must be deployed and not updating."
}
$outputs = Get-RouteWiseOutputs $stack
Write-Host "Verifying the AWS demo before adding the public hostname..."
& "$PSScriptRoot/../check-local.ps1" -BaseUrl "https://$($outputs.DistributionDomainName)"

# Use the deployed template and preserve every unrelated parameter, including
# the AMI, origin token, and any previously configured retention settings.
$parameters = @($stack.Parameters | ForEach-Object {
    if ($_.ParameterKey -eq "WebCustomDomain") { @{ ParameterKey = $_.ParameterKey; ParameterValue = $Domain } }
    elseif ($_.ParameterKey -eq "WebCertificateArn") { @{ ParameterKey = $_.ParameterKey; ParameterValue = $CertificateArn } }
    else { @{ ParameterKey = $_.ParameterKey; UsePreviousValue = $true } }
})
$updated = Invoke-RouteWiseAwsJson -Arguments @("cloudformation", "update-stack") -Payload @{
    StackName = $StackName; UsePreviousTemplate = $true; Parameters = $parameters
    Capabilities = @("CAPABILITY_NAMED_IAM")
} -MissingPattern "No updates are to be performed"
if ($updated) { Wait-RouteWiseStack -StackName $StackName -Creating $false }
$outputs = Get-RouteWiseOutputs (Get-RouteWiseStack $StackName)
Write-Host "`nThe certificate is bound to CloudFront. Public DNS has NOT been changed."
Write-Host "When you are ready, change only this Cloudflare record (DNS only, gray cloud):"
Write-Host "CNAME    $Domain    $($outputs.DistributionDomainName)"
Write-Host "Keep the origin A record and ACM validation CNAME records. Azure resources remain intact."
Write-Host "Then verify: ./scripts/check-local.ps1 -BaseUrl https://$Domain"
Write-Host "Run the AWS deployment workflow again to refresh the backend's allowed origins."
