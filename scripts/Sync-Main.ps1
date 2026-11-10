<#
.SYNOPSIS
    Brings the clone back to an up-to-date main after a PR merges.

.DESCRIPTION
    GitHub deletes a PR's branch when it merges, so the local branch then tracks a ref that no
    longer exists and a plain `git pull` on it fails ("no such ref was fetched"). Run this
    instead, from anywhere in the clone, with no uncommitted changes to tracked files:
      1. Fetches origin and prunes the remote branches deleted on GitHub.
      2. Switches to the default branch (main) and fast-forwards it.
      3. Deletes the local branches whose remote branch is gone and that are merged into it.
         A gone branch that is not merged (a PR closed without merging, or squash-merged) is
         kept and named; delete it yourself with `git branch -D <name>` once you've checked it.

.EXAMPLE
    # PowerShell, in the repository's folder
    ./scripts/Sync-Main.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Native([string] $Command, [string[]] $Arguments) {
    $output = & $Command @Arguments 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "$Command $($Arguments -join ' ') failed:`n$($output -join "`n")" }
    return $output
}

Push-Location (Join-Path $PSScriptRoot '..')
try {
    if (Invoke-Native git @('status', '--porcelain', '--untracked-files=no')) {
        throw 'The working tree has changes: commit or stash them first.'
    }
    $before = (Invoke-Native git @('branch', '--show-current')) -join ''

    # ---- 1. Fetch and prune -------------------------------------------------------------------
    Invoke-Native git @('fetch', '-q', '--prune', 'origin') | Out-Null

    # ---- 2. Default branch, fast-forwarded ------------------------------------------------------
    # origin/HEAD names the default branch; a clone sets it, an older one may need it set.
    $head = & git symbolic-ref -q --short refs/remotes/origin/HEAD
    if ($LASTEXITCODE -ne 0) {
        Invoke-Native git @('remote', 'set-head', 'origin', '--auto') | Out-Null
        $head = Invoke-Native git @('symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD')
    }
    $default = ($head -join '') -replace '^origin/', ''
    if ($before -ne $default) { Invoke-Native git @('switch', '-q', $default) | Out-Null }
    # main never has commits of its own, so a fast-forward is the only expected outcome.
    Invoke-Native git @('merge', '-q', '--ff-only', "origin/$default") | Out-Null
    Write-Host "On $default at $((Invoke-Native git @('log', '-1', '--format=%h %s')) -join '')"

    # ---- 3. Local branches whose remote branch is gone --------------------------------------
    $kept = @()
    foreach ($line in Invoke-Native git @('for-each-ref', '--format=%(refname:short)|%(upstream:track)', 'refs/heads')) {
        $name, $track = $line.Split('|', 2)
        if ($track -ne '[gone]') { continue }
        # -d (not -D) refuses a branch that isn't merged into the default branch.
        & git branch -q -d $name 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "Deleted $name (merged, remote branch gone)" }
        else { $kept += $name }
    }
    if ($kept) {
        Write-Warning ("Kept, not merged into $default although their remote branch is gone: $($kept -join ', ').`n" +
            "Check each one (closed PR, or squash-merged), then: git branch -D <name>")
    }
}
finally {
    Pop-Location
}
