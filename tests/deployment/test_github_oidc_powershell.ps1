[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $PythonExecutable,
    [string] $ConfigureScriptPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:FixturePython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$script:FixturePath = Join-Path $PSScriptRoot "fixtures/github_cli_stub.py"
$script:Passed = 0
$script:Failed = 0
if (-not $ConfigureScriptPath) {
    $ConfigureScriptPath = Join-Path $PSScriptRoot "../../scripts/aws/configure-github-oidc.ps1"
}
$script:ConfigureScript = (Resolve-Path -LiteralPath $ConfigureScriptPath).Path

# Shadow both CLIs. Python preserves genuine native stderr/exit semantics, but
# the fixture has no network code and rejects every unexpected invocation.
function aws {
    & $FixturePython $FixturePath aws @args
    $global:LASTEXITCODE = $LASTEXITCODE
}

function gh {
    if (@($args) -contains "--input") {
        $input | & $FixturePython $FixturePath gh @args
    }
    else {
        & $FixturePython $FixturePath gh @args
    }
    $global:LASTEXITCODE = $LASTEXITCODE
}

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

function Invoke-ConfigurationCase {
    param([string] $Case)
    $env:ROUTEWISE_GITHUB_TEST_CASE = $Case
    $env:ROUTEWISE_GITHUB_TEST_LOG = Join-Path $script:FixtureDirectory "$Case.jsonl"
    $callerPreference = $ErrorActionPreference
    $caught = $null
    try {
        # Omitting EnableDeployment deliberately skips all DNS resolution and
        # must never set the deployment-enabled variable.
        & $script:ConfigureScript -GitHubRepository "offline-owner/RouteWiseFixture" `
            -Region "us-east-1" -Profile "offline profile" `
            -StackName "routewise-offline-fixture" | Out-Null
    }
    catch { $caught = $_ }
    Assert-True ($ErrorActionPreference -eq $callerPreference) "The caller's error preference changed."
    if (-not (Test-Path -LiteralPath $env:ROUTEWISE_GITHUB_TEST_LOG)) {
        throw "The local CLI fixture was not reached: $($caught.Exception.Message)"
    }
    $calls = @(Get-Content -LiteralPath $env:ROUTEWISE_GITHUB_TEST_LOG | ForEach-Object { $_ | ConvertFrom-Json })
    Assert-True (@($calls | Where-Object tool -eq "aws").Count -eq 1) "Only the read-only fixture stack lookup is allowed."
    Assert-True (@($calls | Where-Object { $_.arguments -contains "AWS_DEPLOYMENT_ENABLED" }).Count -eq 0) "Deployment must remain disabled without its explicit switch."
    if ($caught) {
        Assert-True ($caught.Exception.Message -notmatch "OFFLINE-FIXTURE-REJECTED") "The script made an unexpected CLI request."
    }
    return [pscustomobject]@{ Error = $caught; Calls = $calls }
}

function Assert-Variables {
    param([object[]] $Calls)
    $variables = @($Calls | Where-Object { $_.tool -eq "gh" -and $_.arguments[0] -eq "variable" })
    Assert-True ($variables.Count -eq 3) "Exactly the region, stack, and deployment-role variables must be written."
    $expected = @{
        AWS_REGION = "us-east-1"
        AWS_STACK_NAME = "routewise-offline-fixture"
        AWS_DEPLOYMENT_ROLE_ARN = "arn:aws:iam::000000000000:role/routewise-offline-deployment"
    }
    foreach ($name in $expected.Keys) {
        $matches = @($variables | Where-Object { $_.arguments[2] -eq $name })
        Assert-True ($matches.Count -eq 1) "Expected exactly one write of $name."
        Assert-True ($matches[0].arguments[6] -eq $expected[$name]) "The $name value changed."
    }
}

function Assert-Success {
    param([object] $Result)
    if ($null -ne $Result.Error) { throw "The configuration unexpectedly failed: $($Result.Error.Exception.Message)" }
    Assert-Variables $Result.Calls
}

function Assert-NoWrites {
    param([object] $Result)
    Assert-True ($null -ne $Result.Error) "Unsafe existing state must stop setup."
    Assert-True (@($Result.Calls | Where-Object write -eq $true).Count -eq 0) "Failed inspection must not change the environment or variables."
}

$savedEnvironment = @{}
foreach ($name in @("ROUTEWISE_GITHUB_TEST_CASE", "ROUTEWISE_GITHUB_TEST_LOG", "TEMP", "TMP", "TMPDIR", "AWS_PAGER")) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
}
$originalTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$script:FixtureDirectory = Join-Path $originalTempRoot "routewise github fixture $([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $script:FixtureDirectory | Out-Null

try {
    $env:TEMP = $script:FixtureDirectory
    $env:TMP = $script:FixtureDirectory
    $env:TMPDIR = $script:FixtureDirectory
    Write-Host "Offline GitHub OIDC setup regression tests: PowerShell $($PSVersionTable.PSVersion)"
    Assert-True ((Get-Command aws).CommandType -eq "Function") "The AWS fixture must override native AWS executables."
    Assert-True ((Get-Command gh).CommandType -eq "Function") "The GitHub fixture must override native GitHub executables."

    foreach ($case in @("missing", "missing-leading-blank")) {
        Invoke-TestCase "Expected HTTP 404 creates main-only environment before variables ($case)" {
            $result = Invoke-ConfigurationCase $case
            Assert-Success $result
            $writes = @($result.Calls | Where-Object write -eq $true)
            Assert-True ($writes.Count -eq 5) "Creation must perform exactly two protection writes and three variable writes."
            Assert-True ($writes[0].arguments[2] -eq "PUT") "The environment must be created first."
            $body = $writes[0].stdin | ConvertFrom-Json
            Assert-True ($body.deployment_branch_policy.protected_branches -eq $false) "Protected branches alone do not guarantee main-only deployment."
            Assert-True ($body.deployment_branch_policy.custom_branch_policies -eq $true) "Selected branch policies must be enabled."
            Assert-True ($writes[1].arguments[2] -eq "POST") "A branch rule must be created before variables."
            Assert-True ($writes[1].arguments -contains "name=main") "The branch rule must select main."
            Assert-True ($writes[1].arguments -contains "type=branch") "The rule must select a branch, not a tag."
            Assert-True (@($writes[2..4] | Where-Object { $_.arguments[0] -ne "variable" }).Count -eq 0) "Variables must be published last."
        }
    }

    foreach ($case in @("existing", "warning")) {
        Invoke-TestCase "Existing protected environment is accepted without protection edits ($case)" {
            $result = Invoke-ConfigurationCase $case
            Assert-Success $result
            Assert-True (@($result.Calls | Where-Object { $_.write -and $_.arguments[0] -eq "api" }).Count -eq 0) "Existing reviewers, wait timers, and branch protections must be preserved."
            Assert-True ($result.Calls[3].arguments[1] -like "*/deployment-branch-policies") "Existing main-only rules must be checked before publishing variables."
        }
    }

    foreach ($case in @("unauthorized", "forbidden", "server-error")) {
        Invoke-TestCase "Unexpected GitHub inspection failure stops without writes ($case)" {
            $result = Invoke-ConfigurationCase $case
            Assert-NoWrites $result
            $status = @{ unauthorized = "401"; forbidden = "403"; "server-error" = "500" }[$case]
            Assert-True ($result.Error.Exception.Message -match "HTTP\s+$status") "The HTTP failure diagnostic was lost."
            Assert-True ($result.Error.Exception.Message -match "END-GITHUB-DIAGNOSTIC") "The final native stderr diagnostic was lost."
        }
    }

    foreach ($case in @("create-fails", "branch-fails")) {
        Invoke-TestCase "Failed creation stops before variable publication ($case)" {
            $result = Invoke-ConfigurationCase $case
            Assert-True ($null -ne $result.Error) "Creation failure must stop setup."
            $writes = @($result.Calls | Where-Object write -eq $true)
            $expectedWrites = if ($case -eq "create-fails") { 1 } else { 2 }
            Assert-True ($writes.Count -eq $expectedWrites) "Execution did not stop immediately after the failed protection write."
            Assert-True (@($writes | Where-Object { $_.arguments[0] -eq "variable" }).Count -eq 0) "Variables must not be written after a creation failure."
        }
    }

    foreach ($case in @("wrong-branches", "wrong-type", "unrestricted")) {
        Invoke-TestCase "Existing unsafe branch restrictions fail without overwrite ($case)" {
            $result = Invoke-ConfigurationCase $case
            Assert-NoWrites $result
            Assert-True ($result.Error.Exception.Message -match "main") "The failure must explain the required main-only policy."
        }
    }

    Invoke-TestCase "Native stderr capture files are cleaned up" {
        $leftovers = @(Get-ChildItem -LiteralPath $script:FixtureDirectory -Force | Where-Object Extension -ne ".jsonl")
        Assert-True ($leftovers.Count -eq 0) "Temporary native stderr captures were left behind."
    }
}
finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name])
    }
    # Remove only the generated child directory; never remove the temp root.
    $resolvedFixture = [IO.Path]::GetFullPath($script:FixtureDirectory)
    $resolvedTemp = $originalTempRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedFixture.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolvedFixture) -notlike "routewise github fixture *") {
        throw "Refusing to clean an unexpected fixture directory."
    }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}

Write-Host "Passed: $script:Passed. Failed: $script:Failed."
if ($script:Failed -gt 0) { exit 1 }
