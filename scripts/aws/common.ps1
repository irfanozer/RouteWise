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
    # Windows PowerShell 5.1 promotes redirected native stderr to ErrorRecords.
    # Capture it separately so Stop cannot preempt exit-code handling, and a
    # successful command's warnings cannot corrupt its JSON stdout.
    Get-Command aws -ErrorAction Stop | Out-Null
    $PSNativeCommandUseErrorActionPreference = $false
    $stderrPath = [IO.Path]::GetTempFileName()
    $callerErrorPreference = $ErrorActionPreference
    try {
        try {
            $ErrorActionPreference = "Continue"
            $result = & aws @script:AwsArguments @Arguments --output json 2> $stderrPath
            $exitCode = $LASTEXITCODE
        }
        finally { $ErrorActionPreference = $callerErrorPreference }
        $stderrText = [IO.File]::ReadAllText($stderrPath).Trim()
    }
    finally {
        $ErrorActionPreference = $callerErrorPreference
        if (Test-Path -LiteralPath $stderrPath) { Remove-Item -LiteralPath $stderrPath -Force }
    }
    $resultText = ($result | ForEach-Object { "$_" }) -join "`n"
    if ($exitCode -ne 0) {
        $diagnosticText = (@($stderrText, $resultText) | Where-Object { $_ }) -join "`n"
        # PowerShell 5.1 may wrap native ErrorRecord text across lines. Match
        # expected messages independent of wrapping, but retain full diagnostics.
        $matchingText = [regex]::Replace($diagnosticText, '\s+', ' ')
        if ($MissingPattern -and $matchingText -match $MissingPattern) { return $null }
        if (-not $diagnosticText) { $diagnosticText = "AWS CLI returned no diagnostic output." }
        # Do not include arguments: some commands handle confidential values.
        throw "AWS command failed ($($Arguments[0..1] -join ' '), exit $exitCode): $diagnosticText"
    }
    if ($stderrText) { Write-Warning $stderrText }
    if ($resultText.Trim()) { return $resultText | ConvertFrom-Json }
}

function Invoke-RouteWiseGitHub {
    param(
        [Parameter(Mandatory)][string[]] $Arguments,
        [string] $InputJson,
        [switch] $AllowNotFound
    )
    # A missing environment is expected on first setup. In Windows PowerShell
    # 5.1, merged native stderr would throw before we can inspect its exit code.
    Get-Command gh -ErrorAction Stop | Out-Null
    $PSNativeCommandUseErrorActionPreference = $false
    # Windows PowerShell otherwise encodes native stdin as ASCII. This variable
    # is function-local, so the caller's encoding remains unchanged.
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $stderrPath = [IO.Path]::GetTempFileName()
    $callerErrorPreference = $ErrorActionPreference
    try {
        try {
            $ErrorActionPreference = "Continue"
            if ($PSBoundParameters.ContainsKey("InputJson")) {
                $result = $InputJson | & gh @Arguments 2> $stderrPath
            }
            else {
                $result = & gh @Arguments 2> $stderrPath
            }
            $exitCode = $LASTEXITCODE
        }
        finally { $ErrorActionPreference = $callerErrorPreference }
        $stderrText = [IO.File]::ReadAllText($stderrPath).Trim()
    }
    finally {
        $ErrorActionPreference = $callerErrorPreference
        if (Test-Path -LiteralPath $stderrPath) { Remove-Item -LiteralPath $stderrPath -Force }
    }
    $resultText = ($result | ForEach-Object { "$_" }) -join "`n"
    if ($exitCode -ne 0) {
        $diagnosticText = (@($stderrText, $resultText) | Where-Object { $_ }) -join "`n"
        $matchingText = [regex]::Replace($diagnosticText, '\s+', ' ')
        if ($AllowNotFound -and $matchingText -match '\bHTTP 404\b' -and
            $matchingText -notmatch '\bHTTP (?!404\b)\d{3}\b') { return $null }
        if (-not $diagnosticText) { $diagnosticText = "GitHub CLI returned no diagnostic output." }
        # Arguments or request bodies may contain configuration values.
        throw "GitHub command failed (exit $exitCode): $diagnosticText"
    }
    if ($stderrText) { Write-Warning $stderrText }
    return $resultText
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
