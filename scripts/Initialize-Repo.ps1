<#
.SYNOPSIS
    Turns a repository created from embergershared/repo-template into its own project (run once).

.DESCRIPTION
    Run from a clone of the new repository, on its default branch, with a clean tree:
      1. Replaces the placeholders (__PROJECT_NAME__, __REPO__, __DESCRIPTION__, __YEAR__)
         and removes the template-only parts (README banner, the daily Dependabot schedule,
         this script).
      2. Removes the files of a stack the project won't use (see -Stacks).
      3. Sets the GitHub repository: the description (its About), issues on, wiki off,
         branches deleted on merge, the 'phase' label used by the phase issue form, and GitHub
         Actions. When the organization runs Actions in selected repositories only, the script
         adds this one to the list (token scope admin:org); when it can't, it warns and skips
         what needs Actions (CodeQL, the ruleset's required checks). On a public repository,
         also: private vulnerability reporting, Dependabot alerts and security updates, secret
         scanning with push protection, CodeQL default setup, and the 'main' ruleset (PR
         required, with the 'CI result' and 'PR rules' checks). A private repository on GitHub
         Free can't have them: the script says which ones it skipped.
      4. Follows the repository rules for the change itself: opens an issue, commits on
         <prefix>/chore/<issue>-initialize-from-template (files staged one by one), pushes and
         opens the PR that closes the issue, then switches back to the default branch.
    -WhatIf lists what would change, without changing files or GitHub.
    -SkipGitHub only changes the files (steps 1-2); commit them through a PR yourself.

.EXAMPLE
    # PowerShell, in the new repository's folder
    ./scripts/Initialize-Repo.ps1 -Description 'Personal budget tracker' -Stacks dotnet
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    # One line about the project (default: the GitHub repository's description).
    [string] $Description,

    # The stacks the project uses; the files of the other ones are removed.
    [ValidateSet('dotnet', 'python')]
    [string[]] $Stacks = @('dotnet', 'python'),

    # Change the files only: no GitHub settings, issue, commit, push or PR.
    [switch] $SkipGitHub
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
$Template = 'embergershared/repo-template'
# The checks the 'main' ruleset requires: the job names in ci.yml and pr-rules.yml.
$RequiredChecks = @('CI result', 'PR rules')
# Files that describe the placeholders themselves: left as they are.
$KeepPlaceholders = @('scripts/Initialize-Repo.ps1', 'docs/template.md')
$StackFiles = @{
    dotnet = @('global.json', 'Directory.Build.props', 'Directory.Packages.props', 'nuget.config',
        '.github/instructions/dotnet.instructions.md', 'scripts/db/Invoke-EfMigration.ps1')
    python = @('.python-version', 'ruff.toml', '.github/instructions/python.instructions.md',
        'scripts/lock_requirements.py')
}

function Invoke-Native([string] $Command, [string[]] $Arguments) {
    $output = & $Command @Arguments 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "$Command $($Arguments -join ' ') failed:`n$($output -join "`n")" }
    return $output
}

# Returns whether GitHub Actions can run in the repository, turning it on when it can: an
# organization that runs Actions in selected repositories only gets this one added to its list.
function Enable-ActionsForRepo([string] $Repo) {
    $permissions = "repos/$Repo/actions/permissions"
    if ((Invoke-Native gh @('api', $permissions) | ConvertFrom-Json).enabled) { return $true }
    $meta = Invoke-Native gh @('api', "repos/$Repo") | ConvertFrom-Json
    if ($meta.owner.type -ne 'Organization') {
        Write-Warning "GitHub Actions is off in ${Repo}: turn it on in Settings > Actions > General."
        return $false
    }
    try {
        Invoke-Native gh @('api', '-X', 'PUT', "orgs/$($meta.owner.login)/actions/permissions/repositories/$($meta.id)") | Out-Null
    }
    catch {
        # The first line of gh's error says why (scope missing, organization policy).
        Write-Warning ("GitHub Actions is off in $Repo and the script couldn't add it to the selected repositories of " +
            "$($meta.owner.login): $((($_.Exception.Message -split "`n")[1]).TrimEnd('.')). " +
            'See docs/ci-cd.md, "When GitHub Actions is off".')
        return $false
    }
    if (-not (Invoke-Native gh @('api', $permissions) | ConvertFrom-Json).enabled) {
        Write-Warning "$Repo is in the selected repositories of $($meta.owner.login), but GitHub Actions is still off in its Settings > Actions > General."
        return $false
    }
    Write-Host "GitHub: Actions on (added to the selected repositories of $($meta.owner.login))."
    return $true
}

Push-Location $Root
try {
    # ---- Where we are -------------------------------------------------------------------
    $info = Invoke-Native gh @('repo', 'view', '--json', 'nameWithOwner,name,description,owner,defaultBranchRef,visibility') | ConvertFrom-Json
    $repo = $info.nameWithOwner
    if ($repo -eq $Template) { throw "This is $Template itself: run the script in a repository created from it." }
    $defaultBranch = $info.defaultBranchRef.name
    $branch = (Invoke-Native git @('branch', '--show-current')) -join ''
    if ($branch -ne $defaultBranch) { throw "Run it on '$defaultBranch' (now on '$branch')." }
    if (Invoke-Native git @('status', '--porcelain')) { throw 'The working tree has changes: commit or stash them first.' }
    $prefix = switch ($info.owner.login) { 'embergershared' { 'emberger/' } default { '' } }
    if (-not $Description) { $Description = if ($info.description) { $info.description } else { "$($info.name)." } }
    $removed = @('dotnet', 'python') | Where-Object { $_ -notin $Stacks }

    Write-Host "Repository : $repo ($defaultBranch)"
    Write-Host "Description: $Description"
    Write-Host "Stacks     : $($Stacks -join ', ')$(if ($removed) { " (removing $($removed -join ', '))" })"

    # ---- 1. Placeholders and template-only parts ------------------------------------------
    $values = [ordered]@{
        '__PROJECT_NAME__' = $info.name
        '__REPO__'         = $repo
        '__DESCRIPTION__'  = $Description
        '__YEAR__'         = (Get-Date).Year.ToString()
    }
    foreach ($file in Invoke-Native git @('ls-files')) {
        if ($file -in $KeepPlaceholders -or -not (Test-Path $file -PathType Leaf)) { continue }
        $text = [IO.File]::ReadAllText((Join-Path $Root $file))
        if ($text.IndexOf([char]0) -ge 0) { continue }   # binary
        $new = $text
        foreach ($key in $values.Keys) { $new = $new.Replace($key, $values[$key]) }
        if ($file -eq 'README.md') {
            # The banner, its line break and the blank line after it.
            $new = [regex]::Replace($new, '(?s)<!-- template:start -->.*?<!-- template:end -->\r?\n(\r?\n)?', '')
        }
        if ($file -eq '.github/dependabot.yml') {
            # The template checks daily to stay current; a project checks weekly, on Monday.
            $new = [regex]::Replace($new, '(?ms)^( *)# template:start\r?\n.*?^ *# template:end\r?\n',
                "`${1}interval: weekly`n`${1}day: monday`n")
            if ($new.Contains('template:start')) { throw "$file`: the template's daily schedule was not replaced." }
        }
        if ($new -ne $text -and $PSCmdlet.ShouldProcess($file, 'Replace placeholders')) {
            [IO.File]::WriteAllText((Join-Path $Root $file), $new, [Text.UTF8Encoding]::new($false))
        }
    }

    # ---- 2. Stacks not used, and this script ---------------------------------------------
    $toRemove = @($removed | ForEach-Object { $StackFiles[$_] }) + 'scripts/Initialize-Repo.ps1'
    foreach ($file in $toRemove) {
        if ((Test-Path $file) -and $PSCmdlet.ShouldProcess($file, 'Remove')) {
            Invoke-Native git @('rm', '-q', '--', $file) | Out-Null
        }
    }

    if ($SkipGitHub -or $WhatIfPreference) {
        Write-Host "`nFiles changed. Commit them through an issue, its branch (${prefix}chore/<issue>-initialize-from-template) and a PR."
        return
    }

    # ---- 3. GitHub settings -----------------------------------------------------------------
    Invoke-Native gh @('repo', 'edit', $repo, '--description', $Description,
        '--enable-issues', '--enable-wiki=false', '--delete-branch-on-merge') | Out-Null
    Invoke-Native gh @('label', 'create', 'phase', '--repo', $repo, '--color', '5319E7',
        '--description', 'One phase of a planned feature (sub-issue of an umbrella)', '--force') | Out-Null
    Write-Host 'GitHub: description set, issues on, wiki off, branches deleted on merge, label "phase".'
    $actionsOn = Enable-ActionsForRepo $repo

    if ($info.visibility -eq 'PUBLIC') {
        Invoke-Native gh @('api', '-X', 'PUT', "repos/$repo/private-vulnerability-reporting") | Out-Null
        Invoke-Native gh @('api', '-X', 'PUT', "repos/$repo/vulnerability-alerts") | Out-Null
        Invoke-Native gh @('api', '-X', 'PUT', "repos/$repo/automated-security-fixes") | Out-Null
        Invoke-Native gh @('api', '-X', 'PATCH', "repos/$repo",
            '-f', 'security_and_analysis[secret_scanning][status]=enabled',
            '-f', 'security_and_analysis[secret_scanning_push_protection][status]=enabled') | Out-Null
        Write-Host 'GitHub: private vulnerability reporting, Dependabot alerts and security updates, secret scanning with push protection.'
        if ($actionsOn) {
            Invoke-Native gh @('api', '-X', 'PATCH', "repos/$repo/code-scanning/default-setup", '-f', 'state=configured') | Out-Null
            Write-Host 'GitHub: CodeQL default setup.'
        }
        else {
            Write-Warning 'CodeQL default setup skipped: it runs on GitHub Actions.'
        }

        $existing = Invoke-Native gh @('api', "repos/$repo/rulesets", '--jq', '.[].name')
        if ($existing -contains 'main') {
            Write-Host 'GitHub: ruleset "main" already exists, left as it is.'
        }
        else {
            $ruleset = @{
                name        = 'main'
                target      = 'branch'
                enforcement = 'active'
                conditions  = @{ ref_name = @{ include = @('~DEFAULT_BRANCH'); exclude = @() } }
                rules       = @(
                    @{ type = 'deletion' }
                    @{ type = 'non_fast_forward' }
                    @{ type = 'pull_request'; parameters = @{
                            required_approving_review_count   = 0
                            dismiss_stale_reviews_on_push     = $false
                            require_code_owner_review         = $false
                            require_last_push_approval        = $false
                            required_review_thread_resolution = $false
                        }
                    }
                )
            }
            # Without Actions the checks never report, and no PR could be merged.
            if ($actionsOn) {
                $ruleset.rules += @{ type = 'required_status_checks'; parameters = @{
                        strict_required_status_checks_policy = $false
                        required_status_checks               = @($RequiredChecks | ForEach-Object { @{ context = $_ } })
                    }
                }
            }
            $rulesetFile = New-TemporaryFile
            try {
                [IO.File]::WriteAllText($rulesetFile, ($ruleset | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
                Invoke-Native gh @('api', '-X', 'POST', "repos/$repo/rulesets", '--input', $rulesetFile) | Out-Null
            }
            finally { Remove-Item $rulesetFile }
            if ($actionsOn) { Write-Host "GitHub: ruleset ""main"" (PR required; checks: $($RequiredChecks -join ', '))." }
            else { Write-Warning "Ruleset ""main"" created without its required checks ($($RequiredChecks -join ', ')): they run on GitHub Actions." }
        }
    }
    else {
        Write-Warning ("$repo is $($info.visibility.ToLower()): no ruleset, secret scanning, push protection or CodeQL set " +
            '(GitHub Free has them for public repositories only). See docs/ci-cd.md, "Private repositories".')
    }

    # ---- 4. Issue -> branch -> commit -> PR -------------------------------------------------
    $title = 'Initialize the repository from repo-template'
    $issueBody = @"
The repository was created from [$Template](https://github.com/$Template) and still has its placeholders and template-only files.

Expected:
- The project's name, description and year replace the placeholders (README, LICENSE, CHANGELOG, agent rules).
- Stacks: $($Stacks -join ', ')$(if ($removed) { "; the $($removed -join ', ') files are removed" }).
- The template-only parts are gone (README banner, daily Dependabot schedule, ``scripts/Initialize-Repo.ps1``); Dependabot checks weekly.
"@
    $issueUrl = (Invoke-Native gh @('issue', 'create', '--repo', $repo, '--title', $title, '--body', $issueBody)) | Select-Object -Last 1
    $number = $issueUrl.Split('/')[-1]
    $newBranch = "${prefix}chore/$number-initialize-from-template"
    Invoke-Native git @('switch', '-q', '-c', $newBranch) | Out-Null

    foreach ($line in Invoke-Native git @('status', '--porcelain')) {
        $path = $line.Substring(3).Trim('"')
        if ($line.StartsWith(' M') -or $line.StartsWith('M ')) { Invoke-Native git @('add', '--', $path) | Out-Null }
    }
    $message = @"
Repository initialized from repo-template: name, description and stacks set.

Refs #$number

The repository was created from $Template and still had its placeholders.

- README, LICENSE, CHANGELOG and the agent rules (.github/copilot-instructions.md) name $($info.name)
  ($repo).
- Stacks: $($Stacks -join ', ')$(if ($removed) { "; removed the $($removed -join ', ') files" }).
- Removed the template-only parts: the README banner, the daily Dependabot schedule (now weekly, on Monday)
  and scripts/Initialize-Repo.ps1.

Checked: no placeholder left outside docs/template.md.
"@
    # git grep exits 1 when nothing matches: that is the expected result here.
    $left = & git grep -l -e '__PROJECT_NAME__' -e '__REPO__' -e '__DESCRIPTION__' -e '__YEAR__' -- . ':!docs/template.md'
    if ($LASTEXITCODE -eq 0) { throw "Placeholders left in: $($left -join ', ')" }
    $messageFile = New-TemporaryFile
    try {
        [IO.File]::WriteAllText($messageFile, $message, [Text.UTF8Encoding]::new($false))
        Invoke-Native git @('commit', '-q', '-F', $messageFile) | Out-Null
    }
    finally { Remove-Item $messageFile }
    Invoke-Native git @('push', '-q', '-u', 'origin', $newBranch) | Out-Null

    $prBody = @"
Closes #$number

## What
The repository was created from [$Template](https://github.com/$Template).

- Placeholders replaced: name **$($info.name)**, ``$repo``, the description and the year.
- Stacks: $($Stacks -join ', ')$(if ($removed) { "; the $($removed -join ', ') files removed" }).
- Template-only parts removed: the README banner, the daily Dependabot schedule (now weekly, on Monday) and ``scripts/Initialize-Repo.ps1``.

## Tests
- No placeholder left outside ``docs/template.md`` (checked by the script).
- $(if ($actionsOn) { 'CI runs on this PR.' } else { 'CI does not run: GitHub Actions is off in this repository.' })
"@
    $prUrl = (Invoke-Native gh @('pr', 'create', '--repo', $repo, '--base', $defaultBranch, '--head', $newBranch,
            '--title', 'Initialize the repository from repo-template', '--body', $prBody)) | Select-Object -Last 1
    # Back on the default branch: GitHub deletes the PR's branch on merge, and a `git pull` on a
    # branch whose remote is gone fails. Once the PR merges, Sync-Main.ps1 updates it.
    Invoke-Native git @('switch', '-q', $defaultBranch) | Out-Null
    Write-Host "Back on $defaultBranch ($newBranch stays local until the PR merges; then run ./scripts/Sync-Main.ps1)."
    Write-Host "`nIssue: $issueUrl`nPR   : $prUrl"
    Write-Host 'Next: check the PR, merge it, and see docs/template.md ("After the first PR").'
    if (-not $actionsOn) {
        Write-Warning 'GitHub Actions is off: turn it on, then finish the settings it needs (docs/ci-cd.md, "When GitHub Actions is off").'
    }
}
finally {
    Pop-Location
}
