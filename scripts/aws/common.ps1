Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Initialize-RouteWiseAws {
    param([string] $Region = "us-east-1", [string] $Profile = "")
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "Install AWS CLI v2 first." }
    if ($Region -ne "us-east-1") { throw "This deployment currently supports us-east-1, including its CloudFront certificate." }
    $script:AwsArguments = @("--region", $Region, "--no-cli-pager")
    if ($Profile) { $script:AwsArguments += @("--profile", $Profile) }
    $env:AWS_PAGER = ""
}

function Invoke-RouteWiseAws {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $MissingPattern = "")
    # Handle expected missing resources without treating access errors as absence.
    $PSNativeCommandUseErrorActionPreference = $false
    $result = & aws @script:AwsArguments @Arguments --output json 2>&1
    $exitCode = $LASTEXITCODE
    $resultText = ($result | ForEach-Object { "$_" }) -join "`n"
    if ($exitCode -ne 0) {
        if ($MissingPattern -and $resultText -match $MissingPattern) { return $null }
        throw "AWS command failed ($($Arguments[0..1] -join ' ')): $resultText"
    }
    if ($resultText.Trim()) { return $resultText | ConvertFrom-Json }
}

function Invoke-RouteWiseAwsJson {
    param([string[]] $Arguments, [object] $Payload, [string] $MissingPattern = "")
    $requestPath = Join-Path ([IO.Path]::GetTempPath()) "routewise-aws-$([Guid]::NewGuid().ToString('N')).json"
    try {
        [IO.File]::WriteAllText($requestPath, ($Payload | ConvertTo-Json -Depth 40), [Text.UTF8Encoding]::new($false))
        Invoke-RouteWiseAws -Arguments ($Arguments + @("--cli-input-json", "file://$requestPath")) -MissingPattern $MissingPattern
    }
    finally {
        if (Test-Path -LiteralPath $requestPath) { Remove-Item -LiteralPath $requestPath -Force }
    }
}

function Get-RouteWiseStack {
    param([string] $StackName)
    $result = Invoke-RouteWiseAws -Arguments @("cloudformation", "describe-stacks", "--stack-name", $StackName) -MissingPattern "does not exist"
    if ($null -eq $result) { return $null }
    return $result.Stacks[0]
}

function Get-RouteWiseOutputs {
    param([object] $Stack)
    $result = @{}
    foreach ($entry in $Stack.Outputs) { $result[$entry.OutputKey] = $entry.OutputValue }
    return $result
}

function Assert-RouteWiseDomain {
    param([string] $Domain)
    if ($Domain -notmatch '^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$') {
        throw "Supply a lowercase DNS hostname without https://, a path, or a wildcard."
    }
}

function Wait-RouteWiseStack {
    param([string] $StackName, [bool] $Creating)
    $waiter = if ($Creating) { "stack-create-complete" } else { "stack-update-complete" }
    Write-Host "Waiting for AWS infrastructure. CloudFront can take 15 minutes or longer."
    Invoke-RouteWiseAws -Arguments @("cloudformation", "wait", $waiter, "--stack-name", $StackName) | Out-Null
}
