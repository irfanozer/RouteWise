[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $PythonExecutable,
    [string] $CommonScriptPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:FixturePython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$script:FixturePath = Join-Path $PSScriptRoot "fixtures/aws_cli_stub.py"
$script:Passed = 0
$script:Failed = 0

# A function prevents any real AWS executable from being used, while Python
# still exercises the host's native stdout/stderr and exit-code behavior.
function aws {
    & $script:FixturePython $script:FixturePath @args
    $global:LASTEXITCODE = $LASTEXITCODE
}

if (-not $CommonScriptPath) {
    $CommonScriptPath = Join-Path $PSScriptRoot "../../scripts/aws/common.ps1"
}
. $CommonScriptPath
Initialize-RouteWiseAws -Region "us-east-1" -Profile "fixture profile"

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-TestCase {
    param([string] $Name, [scriptblock] $Body)
    try {
        & $Body
        $script:Passed++
        Write-Host "PASS $Name"
    }
    catch {
        $script:Failed++
        Write-Host "FAIL ${Name}: $($_.Exception.Message)"
    }
}

$previousFixtureCase = [Environment]::GetEnvironmentVariable("ROUTEWISE_AWS_TEST_CASE")
$previousTemp = [Environment]::GetEnvironmentVariable("TEMP")
$previousTmp = [Environment]::GetEnvironmentVariable("TMP")
$previousTmpDir = [Environment]::GetEnvironmentVariable("TMPDIR")
$fixtureDirectory = Join-Path ([IO.Path]::GetTempPath()) "routewise native fixture $([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $fixtureDirectory | Out-Null

try {
    $env:TEMP = $fixtureDirectory
    $env:TMP = $fixtureDirectory
    $env:TMPDIR = $fixtureDirectory
    Write-Host "Offline AWS CLI regression tests: PowerShell $($PSVersionTable.PSVersion)"
    Assert-True ((Get-Command aws).CommandType -eq "Function") "The offline AWS fixture must override native AWS executables."

    Invoke-TestCase "Expected missing stack returns null" {
        $env:ROUTEWISE_AWS_TEST_CASE = "missing-stack"
        $result = Get-RouteWiseStack -StackName "routewise-fixture"
        Assert-True ($null -eq $result) "The expected missing-stack result must be null."
        Assert-True ($ErrorActionPreference -eq "Stop") "The error preference was not restored after a missing resource."
    }

    Invoke-TestCase "Leading blank stderr does not hide the AWS service diagnostic" {
        $env:ROUTEWISE_AWS_TEST_CASE = "missing-stack-leading-blank"
        $result = Get-RouteWiseStack -StackName "routewise-fixture"
        Assert-True ($null -eq $result) "A leading blank stderr line hid the expected missing-stack diagnostic."
    }

    Invoke-TestCase "AccessDenied preserves all diagnostics and throws" {
        $env:ROUTEWISE_AWS_TEST_CASE = "access-denied"
        $caught = $null
        try { Get-RouteWiseStack -StackName "routewise-fixture" | Out-Null }
        catch { $caught = $_ }
        Assert-True ($null -ne $caught) "AccessDenied must not be treated as a missing stack."
        Assert-True ($caught.Exception.Message -match "AccessDenied") "The AWS error code was lost."
        Assert-True ($caught.Exception.Message -match "fixture-principal") "Multiline native stderr was truncated."
        $diagnosticWithoutWhitespace = $caught.Exception.Message -replace '\s', ''
        Assert-True ($diagnosticWithoutWhitespace.Contains(("0123456789" * 120))) "A long native stderr diagnostic was truncated."
        Assert-True ($caught.Exception.Message -match "END-DIAGNOSTIC") "The final native stderr diagnostic was lost."
        Assert-True ($ErrorActionPreference -eq "Stop") "The error preference was not restored after AccessDenied."
    }

    Invoke-TestCase "Nonzero exit without diagnostics still fails with its code" {
        $env:ROUTEWISE_AWS_TEST_CASE = "empty-error"
        $caught = $null
        try { Invoke-RouteWiseAws -Arguments @("fixture", "empty-error") | Out-Null }
        catch { $caught = $_ }
        Assert-True ($null -ne $caught) "An empty error response with a nonzero exit must fail."
        Assert-True ($caught.Exception.Message -match "\b7\b") "The native exit code must be included in the failure."
    }

    Invoke-TestCase "Successful JSON is parsed despite native stderr warnings" {
        $env:ROUTEWISE_AWS_TEST_CASE = "warning"
        $result = Invoke-RouteWiseAws -Arguments @("fixture", "warning")
        Assert-True ($result.ok -eq $true) "Native stderr corrupted the stdout JSON response."
        Assert-True ($result.message -eq "stdout JSON remains intact") "The JSON response changed."
        Assert-True ($ErrorActionPreference -eq "Stop") "The error preference was not restored after success."
    }

    Invoke-TestCase "Successful waiter with no output returns null" {
        $env:ROUTEWISE_AWS_TEST_CASE = "empty-success"
        $result = Wait-RouteWiseStack -StackName "routewise-fixture" -Creating $true
        Assert-True ($null -eq $result) "An empty successful waiter response must return null."
    }

    Invoke-TestCase "JSON request paths containing spaces roundtrip and are cleaned up" {
        $env:ROUTEWISE_AWS_TEST_CASE = "echo-json-request"
        $payload = @{ Message = "spaces and 'quotes' remain intact"; Nested = @{ Number = 42 } }
        $result = Invoke-RouteWiseAwsJson -Arguments @("fixture", "echo-json-request") -Payload $payload
        Assert-True ($result.payload.Message -eq $payload.Message) "The JSON string payload did not roundtrip."
        Assert-True ($result.payload.Nested.Number -eq 42) "The nested JSON payload did not roundtrip."
        Assert-True ($result.request_path -like "*routewise native fixture*") "The fixture did not exercise a path with spaces."
        Assert-True (-not (Test-Path -LiteralPath $result.request_path)) "The temporary JSON request was not removed."
    }

    Invoke-TestCase "Caller error preference survives a caught native failure" {
        $env:ROUTEWISE_AWS_TEST_CASE = "access-denied"
        $ErrorActionPreference = "Stop"
        try { Invoke-RouteWiseAws -Arguments @("fixture", "denied") | Out-Null }
        catch { }
        Assert-True ($ErrorActionPreference -eq "Stop") "A native invocation changed its caller's error preference."
    }

    Invoke-TestCase "Temporary native captures are removed after success and failure" {
        Assert-True (@(Get-ChildItem -LiteralPath $fixtureDirectory -Force).Count -eq 0) "Temporary native capture or JSON request files were left behind."
    }
}
finally {
    $env:ROUTEWISE_AWS_TEST_CASE = $previousFixtureCase
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:TMPDIR = $previousTmpDir
    # Delete only this test's verified generated directory, never its parent.
    $resolvedFixture = [IO.Path]::GetFullPath($fixtureDirectory)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedFixture.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolvedFixture) -notlike "routewise native fixture *") {
        throw "Refusing to clean an unexpected fixture directory."
    }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}

Write-Host "Passed: $script:Passed. Failed: $script:Failed."
if ($script:Failed -gt 0) { exit 1 }
# Expected native failures must not become GitHub Actions' final step exit code.
exit 0
