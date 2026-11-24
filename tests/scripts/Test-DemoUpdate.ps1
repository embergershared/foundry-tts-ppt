#Requires -Version 7.0
<#
.SYNOPSIS
Tests scripts/DemoUpdate.psm1 (issue #35) on scratch repositories: no network, nothing of this
clone is touched.

.DESCRIPTION
  A bare "origin", a clone (the demo's), and a second clone that pushes new commits to main:
  1. On a work branch, behind origin: switched to main and fast-forwarded.
  2. Up to date: nothing changes.
  3. Uncommitted changes on a work branch: it stops, the branch and the change are kept.
  4. main with a commit of its own: it stops, the commit is kept.
  5. origin unreachable: a warning, and it still switches to the local main.
  6. Get-MainCheckout from a linked worktree gives the main clone.
Run it from anywhere: PowerShell 7 with git.
#>
[CmdletBinding()]
param(
    [string] $WorkFolder = (Join-Path ([System.IO.Path]::GetTempPath()) 'demo-update-test')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Import-Module (Join-Path $root 'scripts\DemoUpdate.psm1') -Force
$failures = 0

function Assert-True([bool] $Condition, [string] $Name) {
    if ($Condition) { Write-Host "PASS  $Name" }
    else { Write-Host "FAIL  $Name" -ForegroundColor Red; $script:failures++ }
}

# Not named Git: PowerShell names ignore case, so a function Git would call itself instead of git.
function Invoke-TestGit([string] $Folder) {
    $output = & git.exe -C $Folder @args 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "git $args failed in ${Folder}: $output" }
    $output
}

function New-Commit([string] $Folder, [string] $File, [string] $Text) {
    Set-Content -LiteralPath (Join-Path $Folder $File) -Value $Text
    Invoke-TestGit $Folder add -- $File | Out-Null
    Invoke-TestGit $Folder commit -q -m "Changed $File." | Out-Null
}

# Scratch commits need an author; the environment gives one without touching any git config.
$env:GIT_AUTHOR_NAME = $env:GIT_COMMITTER_NAME = 'Demo update test'
$env:GIT_AUTHOR_EMAIL = $env:GIT_COMMITTER_EMAIL = 'demo-update-test@example.invalid'

if (Test-Path $WorkFolder) { Remove-Item $WorkFolder -Recurse -Force }
New-Item -ItemType Directory -Path $WorkFolder | Out-Null
$origin = Join-Path $WorkFolder 'origin.git'
$demo = Join-Path $WorkFolder 'demo'
$other = Join-Path $WorkFolder 'other'
Invoke-TestGit $WorkFolder init -q --bare -b main $origin | Out-Null
Invoke-TestGit $WorkFolder clone -q $origin $demo | Out-Null
New-Commit $demo 'readme.txt' 'first'
Invoke-TestGit $demo push -q origin main | Out-Null
Invoke-TestGit $WorkFolder clone -q $origin $other | Out-Null

# 1. A work branch, behind origin
Invoke-TestGit $demo switch -q -c emberger/feature/1-work | Out-Null
New-Commit $demo 'work.txt' 'work in progress'
New-Commit $other 'readme.txt' 'second'
Invoke-TestGit $other push -q origin main | Out-Null
$result = Update-CloneToMain -Root $demo
Assert-True ((Invoke-TestGit $demo branch --show-current) -eq 'main') 'a work branch: switched to main'
Assert-True ((Invoke-TestGit $demo rev-parse HEAD) -eq (Invoke-TestGit $other rev-parse HEAD)) 'behind: fast-forwarded to origin/main'
Assert-True ($result.Changed -and $result.Summary -like "Switched from 'emberger/feature/1-work' to main*") "it says so: $($result.Summary)"
Assert-True ((Invoke-TestGit $demo branch --list emberger/feature/1-work) -ne $null) 'the work branch is kept'

# 2. Up to date
$result = Update-CloneToMain -Root $demo
Assert-True (-not $result.Changed -and $result.Summary -like 'On main, up to date*') "up to date: nothing changes ($($result.Summary))"
New-Commit $other 'readme.txt' 'third'
Invoke-TestGit $other push -q origin main | Out-Null
$result = Update-CloneToMain -Root $demo
Assert-True ($result.Changed -and $result.Summary -like 'Updated main from*') "on main, behind: updated ($($result.Summary))"

# 3. Uncommitted changes on a work branch
Invoke-TestGit $demo switch -q emberger/feature/1-work | Out-Null
Set-Content -LiteralPath (Join-Path $demo 'work.txt') -Value 'not committed'
$stopped = $null
try { Update-CloneToMain -Root $demo | Out-Null } catch { $stopped = $_.Exception.Message }
Assert-True ($stopped -like '*uncommitted changes*-NoUpdate*') 'uncommitted changes on a branch: it stops and says what to do'
Assert-True ((Invoke-TestGit $demo branch --show-current) -eq 'emberger/feature/1-work') 'uncommitted changes: still on the branch'
Assert-True ((Get-Content -LiteralPath (Join-Path $demo 'work.txt')) -eq 'not committed') 'uncommitted changes: kept'
Invoke-TestGit $demo checkout -q -- work.txt | Out-Null
Set-Content -LiteralPath (Join-Path $demo 'new-untracked.txt') -Value 'untracked'
$result = Update-CloneToMain -Root $demo
Assert-True ($result.Changed -and (Test-Path (Join-Path $demo 'new-untracked.txt'))) 'an untracked file doesn''t stop it, and stays'

# 4. main with a commit of its own
New-Commit $demo 'local.txt' 'committed on main by mistake'
$stopped = $null
try { Update-CloneToMain -Root $demo | Out-Null } catch { $stopped = $_.Exception.Message }
Assert-True ($stopped -like "*1 commit(s) that aren't on GitHub*") 'main ahead of origin: it stops'
Assert-True ((Invoke-TestGit $demo log -1 --format=%s) -eq 'Changed local.txt.') 'main ahead: the commit is kept'
Invoke-TestGit $demo reset -q --hard origin/main | Out-Null

# 5. origin unreachable
Invoke-TestGit $demo switch -q emberger/feature/1-work | Out-Null
Invoke-TestGit $demo remote set-url origin (Join-Path $WorkFolder 'missing.git') | Out-Null
$result = Update-CloneToMain -Root $demo -WarningVariable warned -WarningAction SilentlyContinue
Assert-True (-not $result.Fetched -and @($warned).Count -eq 1) 'offline: a warning'
Assert-True ((Invoke-TestGit $demo branch --show-current) -eq 'main') 'offline: still switched to the local main'
Invoke-TestGit $demo remote set-url origin $origin | Out-Null

# 6. From a linked worktree
$linked = Join-Path $WorkFolder 'demo-feature'
Invoke-TestGit $demo worktree add -q $linked emberger/feature/1-work | Out-Null
Assert-True ((Get-MainCheckout -Root $linked) -eq [System.IO.Path]::GetFullPath($demo)) 'from a worktree: the main clone'
Assert-True ((Get-MainCheckout -Root $demo) -eq [System.IO.Path]::GetFullPath($demo)) 'from the main clone: itself'

Remove-Item $WorkFolder -Recurse -Force
if ($failures) {
    Write-Host "$failures check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.'
