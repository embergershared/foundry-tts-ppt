<#
.SYNOPSIS
    EF Core migrations for a SQLite database: backup first, trial on a copy, and a way back.

.DESCRIPTION
    Add       dotnet ef migrations add <Name>; warns when Down() is empty (no way back) or when
              Up() drops, renames or alters something (split it into additive steps).
    Script    SQL of the migrations still to apply, saved in artifacts/migrations/
              for review (and for the PR's Database section).
    Apply     applies the pending migrations:
                1. backup of the database (sqlite_backup.py, WAL-safe, checked)
                2. trial on a copy: migrate the copy, compare row counts with the backup
                3. confirmation, then the real database
                4. on failure: the backup is restored and checked, and the script stops
    Rollback  the same steps, migrating down to -TargetMigration ('0' = before the first one).

    Needs the dotnet-ef tool (a local tool: dotnet new tool-manifest; dotnet tool install
    dotnet-ef --version <your EF Core version>) and Python 3 for scripts/db/sqlite_backup.py
    (the project's .venv when there is one). The DbContext must use UseSqlite: the database
    is chosen with --connection "Data Source=<file>".

.EXAMPLE
    # PowerShell, from the repository root
    ./scripts/db/Invoke-EfMigration.ps1 -Action Add -Name AddCardHistory -Project src/App.Data -StartupProject src/App
    ./scripts/db/Invoke-EfMigration.ps1 -Action Apply -Project src/App.Data -StartupProject src/App -DatabasePath data/app.db
    ./scripts/db/Invoke-EfMigration.ps1 -Action Rollback -TargetMigration AddCards -Project src/App.Data -StartupProject src/App -DatabasePath data/app.db
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Add', 'Script', 'Apply', 'Rollback')]
    [string] $Action,

    # Project that holds the DbContext and its migrations.
    [Parameter(Mandatory)]
    [string] $Project,

    # Project that is run to build the DbContext (default: -Project).
    [string] $StartupProject,

    # DbContext class, when the project has several.
    [string] $Context,

    # Add: the migration's name, e.g. AddCardHistory.
    [string] $Name,

    # Rollback: the migration to go back to ('0' = before the first migration).
    [string] $TargetMigration,

    # Folder of the migrations inside -Project (Add only).
    [string] $OutputDir = 'Migrations',

    # SQLite database file (Apply, Rollback; Script uses it to start from what is applied).
    [string] $DatabasePath,

    # Go on even when the trial run lost rows in an existing table.
    [switch] $AllowRowLoss
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..' '..')
$SqliteTool = Join-Path $PSScriptRoot 'sqlite_backup.py'
$Artifacts = Join-Path $RepoRoot 'artifacts' 'migrations'
if (-not $StartupProject) { $StartupProject = $Project }

function Write-Step([string] $Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

function Get-Python {
    foreach ($candidate in @('.venv/Scripts/python.exe', '.venv/bin/python')) {
        $path = Join-Path $RepoRoot $candidate
        if (Test-Path $path) { return @($path) }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @('py', '-3') }
    if (Get-Command python3 -ErrorAction SilentlyContinue) { return @('python3') }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @('python') }
    throw 'Python 3 not found: create the project .venv or install Python 3.'
}

function Invoke-SqliteTool([string[]] $Arguments) {
    $python = @(Get-Python)
    $pythonArgs = @($python | Select-Object -Skip 1)
    $output = & $python[0] @pythonArgs $SqliteTool @Arguments 2>&1 | ForEach-Object { "$_" }
    $output | ForEach-Object { Write-Host "  $_" }
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $output }
}

function Invoke-Ef([string[]] $Arguments, [switch] $Quiet) {
    $common = @('--project', $Project, '--startup-project', $StartupProject, '--no-build')
    if ($Context) { $common += @('--context', $Context) }
    $output = & dotnet ef @Arguments @common 2>&1 | ForEach-Object { "$_" }
    if (-not $Quiet -or $LASTEXITCODE -ne 0) { $output | ForEach-Object { Write-Host "  $_" } }
    if ($LASTEXITCODE -ne 0) { throw "dotnet ef $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
    return $output
}

function Get-Migrations([string] $Database) {
    # --prefix-output marks the JSON lines with "data:", whatever else the tool prints.
    $lines = Invoke-Ef @('migrations', 'list', '--json', '--prefix-output', '--connection', "Data Source=$Database") -Quiet
    $json = ($lines | Where-Object { $_ -like 'data:*' } | ForEach-Object { $_.Substring(5).Trim() }) -join "`n"
    return @($json | ConvertFrom-Json)
}

function Update-Database([string] $Target, [string] $Database) {
    # No target = the latest migration.
    $arguments = @('database', 'update')
    if ($Target) { $arguments += $Target }
    Invoke-Ef ($arguments + @('--connection', "Data Source=$Database")) | Out-Null
}

function Test-Prerequisites {
    $null = & dotnet ef --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'dotnet-ef not found: dotnet new tool-manifest; dotnet tool install dotnet-ef --version <your EF Core version>'
    }
    Write-Step "Build $StartupProject"
    dotnet build $StartupProject --nologo -v quiet
    if ($LASTEXITCODE -ne 0) { throw 'Build failed: nothing migrated.' }
}

function Invoke-SafeMigration([string] $Target, [string] $Reason) {
    if (-not $DatabasePath) { throw "-DatabasePath is required for $Action." }
    $database = [IO.Path]::GetFullPath($DatabasePath)
    New-Item -ItemType Directory -Force -Path $Artifacts -WhatIf:$false | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'

    if (-not (Test-Path $database)) {
        Write-Step "No database at $database yet: a fresh one is created and migrated (nothing to back up)"
        if ($PSCmdlet.ShouldProcess($database, 'Create and migrate a new database')) {
            Update-Database $Target $database
            Invoke-SqliteTool @('verify', $database) | Out-Null
        }
        return
    }

    $migrations = Get-Migrations $database
    $applied = @($migrations | Where-Object applied)
    $current = if ($applied) { $applied[-1].id } else { '0' }
    if ($Action -eq 'Apply') {
        $todo = @($migrations | Where-Object { -not $_.applied })
        if (-not $todo) { Write-Step 'The database is up to date: nothing to apply'; return }
        Write-Host "Pending: $($todo.name -join ', ')"
        $Target = $todo[-1].id
        $Reason = $todo[-1].name
    }
    elseif ($current -eq $Target -or ($Target -eq '0' -and -not $applied)) {
        Write-Step "Already at $Target"; return
    }

    Write-Step "1. Backup of $database"
    $backup = Invoke-SqliteTool @('backup', $database, '--reason', $Reason)
    if ($backup.ExitCode -ne 0) { throw 'Backup failed: nothing migrated.' }
    $backupPath = ($backup.Output | Where-Object { $_ -like 'BACKUP_PATH=*' } | Select-Object -Last 1).Substring(12)

    Write-Step "2. Trial on a copy ($current -> $Target)"
    $trial = Join-Path $Artifacts "trial_$stamp.db"
    if ((Invoke-SqliteTool @('copy', $backupPath, $trial)).ExitCode -ne 0) { throw 'Trial copy failed: nothing migrated.' }
    try { Update-Database $Target $trial }
    catch { throw "The trial migration failed (see above): the real database was not changed. Backup: $backupPath" }
    $compare = Invoke-SqliteTool @('compare', $backupPath, $trial)
    if ($compare.ExitCode -ne 0 -and -not $AllowRowLoss) {
        throw "The trial lost rows (see above): the real database was not changed. Rerun with -AllowRowLoss only if that loss is intended. Trial copy: $trial"
    }
    $sql = Join-Path $Artifacts "${stamp}_$($current)_to_$Target.sql"
    if ($Target -ne '0' -and $Action -eq 'Apply') {
        Invoke-Ef @('migrations', 'script', $current, $Target, '--output', $sql) -Quiet | Out-Null
        Write-Host "  SQL for review: $sql"
    }

    Write-Step "3. Migrate $database ($current -> $Target)"
    if (-not $PSCmdlet.ShouldProcess($database, "Migrate from $current to $Target")) {
        Write-Host "Not migrated. Backup: $backupPath"
        return
    }
    try {
        Update-Database $Target $database
    }
    catch {
        Write-Step '4. FAILED: restoring the backup'
        $restore = Invoke-SqliteTool @('restore', $backupPath, $database)
        $state = if ($restore.ExitCode -eq 0) { 'restored and checked' } else { 'NOT restored: restore it by hand' }
        throw "Migration failed ($($_.Exception.Message)); database $state from $backupPath"
    }

    Write-Step '4. Check the migrated database'
    $verify = Invoke-SqliteTool @('verify', $database)
    $after = Invoke-SqliteTool @('compare', $backupPath, $database)
    if ($verify.ExitCode -ne 0 -or ($after.ExitCode -ne 0 -and -not $AllowRowLoss)) {
        Write-Step 'Checks FAILED: restoring the backup'
        Invoke-SqliteTool @('restore', $backupPath, $database) | Out-Null
        throw "The migrated database failed its checks; restored from $backupPath"
    }

    Write-Step 'Done'
    Write-Host "Backup : $backupPath"
    Write-Host "Way back: ./scripts/db/Invoke-EfMigration.ps1 -Action Rollback -TargetMigration $current -Project $Project -StartupProject $StartupProject -DatabasePath $DatabasePath"
    Write-Host "     or : python scripts/db/sqlite_backup.py restore `"$backupPath`" `"$DatabasePath`""
}

Push-Location $RepoRoot
try {
    switch ($Action) {
        'Add' {
            if (-not $Name) { throw '-Name is required for Add.' }
            Test-Prerequisites
            Write-Step "Add migration $Name"
            Invoke-Ef @('migrations', 'add', $Name, '--output-dir', $OutputDir) | Out-Null
            $file = Get-ChildItem -Path (Join-Path $Project $OutputDir) -Filter "*_$Name.cs" |
                Where-Object Name -notlike '*.Designer.cs' | Sort-Object Name | Select-Object -Last 1
            $code = Get-Content $file.FullName -Raw
            $down = [regex]::Match($code, 'void Down\(MigrationBuilder migrationBuilder\)\s*\{(?<body>[\s\S]*?)\n\s{8}\}').Groups['body'].Value
            if ($down.Trim() -eq '') { Write-Warning "Down() is empty in $($file.Name): write the way back before applying it." }
            $up = [regex]::Match($code, 'void Up\(MigrationBuilder migrationBuilder\)\s*\{(?<body>[\s\S]*?)\n\s{8}\}').Groups['body'].Value
            $destructive = [regex]::Matches($up, '\.(DropTable|DropColumn|RenameTable|RenameColumn|AlterColumn|DropIndex|DropForeignKey|Sql)\(') |
                ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
            if ($destructive) {
                Write-Warning "Up() is destructive ($($destructive -join ', ')): split it into additive steps (add, copy, switch, drop later) and get a go-ahead before applying it."
            }
            Write-Host "Created $($file.FullName)"
            Write-Host 'Next: review Up() and Down(), then -Action Script and -Action Apply.'
        }
        'Script' {
            Test-Prerequisites
            New-Item -ItemType Directory -Force -Path $Artifacts -WhatIf:$false | Out-Null
            $from = '0'
            if ($DatabasePath -and (Test-Path $DatabasePath)) {
                $applied = @(Get-Migrations ([IO.Path]::GetFullPath($DatabasePath)) | Where-Object applied)
                if ($applied) { $from = $applied[-1].id }
            }
            $sql = Join-Path $Artifacts "$(Get-Date -Format 'yyyyMMdd_HHmmss')_from_$from.sql"
            Invoke-Ef @('migrations', 'script', $from, '--output', $sql) -Quiet | Out-Null
            Write-Host "SQL from $from to the latest migration: $sql"
        }
        'Apply' {
            Test-Prerequisites
            Invoke-SafeMigration -Target '' -Reason ''
        }
        'Rollback' {
            if (-not $TargetMigration) { throw "-TargetMigration is required for Rollback ('0' = before the first migration)." }
            Test-Prerequisites
            Invoke-SafeMigration -Target $TargetMigration -Reason "rollback-to-$TargetMigration"
        }
    }
}
finally {
    Pop-Location
}
