#Requires -Version 7.0
<#
.SYNOPSIS
    Keeps the demo on an up-to-date main (issue #35), for scripts/Start-Demo.ps1.

.DESCRIPTION
    The launcher runs whatever the clone has checked out, so a clone left on a work branch, or
    behind GitHub, ran stale code. Before the demo starts:
      Get-MainCheckout     the main clone's folder, even when the launcher was started from a
                           linked worktree (its first `git worktree list` entry).
      Update-CloneToMain   fetches origin, switches to main, fast-forwards it to origin/main.
    It never loses work: it stops (throws) with uncommitted changes to tracked files on another
    branch, or when main can't be fast-forwarded. Without a network it warns and keeps the local
    main. tests/scripts/Test-DemoUpdate.ps1 tests it on scratch repositories.
#>

Set-StrictMode -Version Latest

function Invoke-Git {
    <# Runs git in a folder; returns its output lines, or throws with them when it fails. #>
    param([Parameter(Mandatory)] [string] $Root, [Parameter(Mandatory)] [string[]] $Arguments, [switch] $AllowFailure)
    $output = @(& git -C $Root @Arguments 2>&1 | ForEach-Object { "$_" })
    if ($LASTEXITCODE -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed in ${Root}:`n$($output -join "`n")"
    }
    , $output
}

function Get-MainCheckout {
    <# The main clone's folder: the first working tree git lists, whichever worktree Root is. #>
    param([Parameter(Mandatory)] [string] $Root)
    $lines = Invoke-Git -Root $Root -Arguments @('worktree', 'list', '--porcelain')
    $first = if ($lines.Count) { $lines[0] } else { '' }
    if ($first -notmatch '^worktree (.+)$') { throw "git worktree list gave no folder for ${Root}: '$first'" }
    [System.IO.Path]::GetFullPath($Matches[1])
}

function Update-CloneToMain {
    <# Brings the clone at Root to an up-to-date Branch (main). Returns what it did:
       Before / After (branch and commit), Changed (anything moved), Fetched, Summary. #>
    param([Parameter(Mandatory)] [string] $Root, [string] $Branch = 'main', [string] $Remote = 'origin')
    $headBefore = (Invoke-Git -Root $Root -Arguments @('rev-parse', 'HEAD')) -join ''
    $current = (Invoke-Git -Root $Root -Arguments @('branch', '--show-current')) -join ''
    $before = if ($current) { $current } else { "detached at $($headBefore.Substring(0, 7))" }

    Invoke-Git -Root $Root -Arguments @('fetch', '-q', '--prune', $Remote) -AllowFailure | Out-Null
    $fetched = $LASTEXITCODE -eq 0
    if (-not $fetched) {
        Write-Warning "Could not reach $Remote (no network?): the demo runs the local $Branch, which may be behind GitHub."
    }

    if ($current -ne $Branch) {
        $changes = Invoke-Git -Root $Root -Arguments @('status', '--porcelain', '--untracked-files=no')
        if ($changes) {
            throw ("The clone at $Root is on '$before' with uncommitted changes ($($changes.Count) file(s)), so it " +
                "can't switch to $Branch without risking them. Commit or stash them (git stash), then start " +
                "the demo again; or start it with -NoUpdate to run '$before' as it is.")
        }
        Invoke-Git -Root $Root -Arguments @('switch', '-q', $Branch) | Out-Null
    }

    if ($fetched) {
        $ahead = [int] ((Invoke-Git -Root $Root -Arguments @('rev-list', '--count', "$Remote/$Branch..$Branch")) -join '')
        if ($ahead -gt 0) {
            throw ("$Branch at $Root has $ahead commit(s) that aren't on GitHub ($Remote/$Branch), so it can't be " +
                "fast-forwarded. Changes reach $Branch only through a PR: move them to a branch, then reset " +
                "$Branch to $Remote/$Branch; or start the demo with -NoUpdate.")
        }
        $merge = Invoke-Git -Root $Root -Arguments @('merge', '-q', '--ff-only', "$Remote/$Branch") -AllowFailure
        if ($LASTEXITCODE -ne 0) {
            throw ("$Branch at $Root couldn't be fast-forwarded to $Remote/${Branch}:`n$($merge -join "`n")`n" +
                "Usually local changes to files the update touches: commit or stash them, or start with -NoUpdate.")
        }
    }

    $headAfter = (Invoke-Git -Root $Root -Arguments @('rev-parse', 'HEAD')) -join ''
    $subject = (Invoke-Git -Root $Root -Arguments @('log', '-1', '--format=%h %s')) -join ''
    $changed = ($current -ne $Branch) -or ($headAfter -ne $headBefore)
    $summary = if (-not $changed) { "On $Branch, up to date: $subject" }
    elseif ($current -ne $Branch) { "Switched from '$before' to $Branch, now at: $subject" }
    else { "Updated $Branch from $($headBefore.Substring(0, 7)) to: $subject" }
    [pscustomobject]@{
        Before  = $before
        After   = $Branch
        Changed = $changed
        Fetched = $fetched
        Summary = $summary
    }
}

Export-ModuleMember -Function Get-MainCheckout, Update-CloneToMain
