# LoomAgentTools.psm1
# Advanced PowerShell helper functions for Loom AI agents
# Loaded automatically into agent REPL sessions

#Requires -Version 7.0

# ─── File Operations ────────────────────────────────────────────

function Read-LoomFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Path,
        [int]$MaxLines = 0
    )
    if (-not (Test-Path $Path)) {
        return @{ success = $false; error = "File not found: $Path" } | ConvertTo-Json -Compress
    }
    $content = Get-Content -Path $Path -Raw
    $lines = Get-Content -Path $Path
    if ($MaxLines -gt 0) { $lines = $lines | Select-Object -First $MaxLines }
    $numbered = for ($i = 0; $i -lt $lines.Count; $i++) {
        "{0,5}| {1}" -f ($i + 1), $lines[$i]
    }
    @{
        success = $true
        path = (Resolve-Path $Path).Path
        line_count = (Get-Content -Path $Path).Count
        content = ($numbered -join "`n")
    } | ConvertTo-Json -Compress
}

function Write-LoomFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Path,
        [Parameter(Mandatory, Position = 1)]
        [string]$Content
    )
    $parent = Split-Path -Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Set-Content -Path $Path -Value $Content -Encoding UTF8
    @{ success = $true; path = (Resolve-Path $Path).Path; bytes = (Get-Item $Path).Length } | ConvertTo-Json -Compress
}

function Search-LoomCode {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Pattern,
        [string]$Path = ".",
        [string]$Include = "*.*",
        [int]$MaxResults = 50
    )
    $results = Get-ChildItem -Path $Path -Recurse -File -Include $Include -ErrorAction SilentlyContinue |
        Select-String -Pattern $Pattern -ErrorAction SilentlyContinue |
        Select-Object -First $MaxResults |
        ForEach-Object {
            @{
                file = $_.Path
                line = $_.LineNumber
                text = $_.Line.Trim()
            }
        }
    @{ success = $true; pattern = $Pattern; count = ($results | Measure-Object).Count; matches = $results } | ConvertTo-Json -Compress -Depth 3
}

function Find-LoomFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Pattern,
        [string]$Path = ".",
        [int]$MaxResults = 100
    )
    $files = Get-ChildItem -Path $Path -Recurse -File -Filter $Pattern -ErrorAction SilentlyContinue |
        Select-Object -First $MaxResults |
        ForEach-Object {
            @{
                name = $_.Name
                path = $_.FullName
                size = $_.Length
                modified = $_.LastWriteTime.ToString("o")
            }
        }
    @{ success = $true; pattern = $Pattern; count = ($files | Measure-Object).Count; files = $files } | ConvertTo-Json -Compress -Depth 3
}

# ─── Git Operations ─────────────────────────────────────────────

function Get-LoomGitStatus {
    [CmdletBinding()]
    param()
    $status = git status --porcelain 2>&1
    $branch = git branch --show-current 2>&1
    $ahead_behind = git rev-list --left-right --count "HEAD...@{upstream}" 2>&1
    @{
        success = $true
        branch = $branch
        changes = ($status -split "`n" | Where-Object { $_ } | ForEach-Object {
            @{ status = $_.Substring(0, 2).Trim(); file = $_.Substring(3) }
        })
        ahead_behind = $ahead_behind
    } | ConvertTo-Json -Compress -Depth 3
}

function Get-LoomGitDiff {
    [CmdletBinding()]
    param(
        [string]$Path,
        [switch]$Staged
    )
    $args_list = @("diff")
    if ($Staged) { $args_list += "--staged" }
    if ($Path) { $args_list += "--", $Path }
    $diff = & git @args_list 2>&1
    @{ success = $true; diff = ($diff -join "`n") } | ConvertTo-Json -Compress
}

function New-LoomGitCommit {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Message
    )
    git add -A 2>&1 | Out-Null
    $result = git commit -m $Message 2>&1
    @{ success = ($LASTEXITCODE -eq 0); output = ($result -join "`n") } | ConvertTo-Json -Compress
}

function Get-LoomGitLog {
    [CmdletBinding()]
    param([int]$Limit = 20)
    $log = git log --oneline -n $Limit --format="%H|%h|%s|%an|%ai" 2>&1
    $entries = $log -split "`n" | Where-Object { $_ } | ForEach-Object {
        $parts = $_ -split '\|', 5
        @{ hash = $parts[0]; short = $parts[1]; message = $parts[2]; author = $parts[3]; date = $parts[4] }
    }
    @{ success = $true; count = ($entries | Measure-Object).Count; commits = $entries } | ConvertTo-Json -Compress -Depth 3
}

function Save-LoomGitStash {
    [CmdletBinding()]
    param([string]$Message = "Loom auto-stash")
    $result = git stash push -m $Message 2>&1
    @{ success = ($LASTEXITCODE -eq 0); output = ($result -join "`n") } | ConvertTo-Json -Compress
}

function Restore-LoomGitStash {
    [CmdletBinding()]
    param()
    $result = git stash pop 2>&1
    @{ success = ($LASTEXITCODE -eq 0); output = ($result -join "`n") } | ConvertTo-Json -Compress
}

# ─── System Info ────────────────────────────────────────────────

function Get-LoomGpuStatus {
    [CmdletBinding()]
    param()
    try {
        $nvsmi = nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv,noheader 2>&1
        if ($LASTEXITCODE -eq 0) {
            $parts = ($nvsmi -split ',').Trim()
            return @{
                success = $true
                gpu = $parts[0]
                memory_total = $parts[1]
                memory_used = $parts[2]
                memory_free = $parts[3]
                utilization = $parts[4]
                temperature = $parts[5]
            } | ConvertTo-Json -Compress
        }
    } catch {}
    @{ success = $false; error = "nvidia-smi not available" } | ConvertTo-Json -Compress
}

function Get-LoomDiskUsage {
    [CmdletBinding()]
    param([string]$Path = ".")
    $drive = (Get-Item $Path).PSDrive
    $info = Get-PSDrive -Name $drive.Name
    @{
        success = $true
        drive = $drive.Name
        used_gb = [math]::Round($info.Used / 1GB, 2)
        free_gb = [math]::Round($info.Free / 1GB, 2)
        total_gb = [math]::Round(($info.Used + $info.Free) / 1GB, 2)
    } | ConvertTo-Json -Compress
}

function Get-LoomMemoryUsage {
    [CmdletBinding()]
    param()
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($os) {
        @{
            success = $true
            total_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
            free_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
            used_gb = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 2)
        } | ConvertTo-Json -Compress
    } else {
        @{ success = $false; error = "Unable to query memory info" } | ConvertTo-Json -Compress
    }
}

# ─── Build & Test ───────────────────────────────────────────────

function Invoke-LoomBuild {
    [CmdletBinding()]
    param([string]$Command)
    if (-not $Command) {
        if (Test-Path "package.json") { $Command = "npm run build" }
        elseif (Test-Path "pyproject.toml") { $Command = "python -m build" }
        elseif (Test-Path "Cargo.toml") { $Command = "cargo build" }
        elseif (Test-Path "Makefile") { $Command = "make" }
        else { return @{ success = $false; error = "No build system detected" } | ConvertTo-Json -Compress }
    }
    $output = Invoke-Expression $Command 2>&1
    @{ success = ($LASTEXITCODE -eq 0); command = $Command; output = ($output -join "`n") } | ConvertTo-Json -Compress
}

function Invoke-LoomTest {
    [CmdletBinding()]
    param(
        [string]$Filter,
        [string]$Command
    )
    if (-not $Command) {
        if (Test-Path "pyproject.toml") { $Command = "python -m pytest" }
        elseif (Test-Path "package.json") { $Command = "npm test" }
        elseif (Test-Path "Cargo.toml") { $Command = "cargo test" }
        else { return @{ success = $false; error = "No test framework detected" } | ConvertTo-Json -Compress }
    }
    if ($Filter) { $Command += " -k `"$Filter`"" }
    $output = Invoke-Expression $Command 2>&1
    @{ success = ($LASTEXITCODE -eq 0); command = $Command; output = ($output -join "`n") } | ConvertTo-Json -Compress
}

# ─── Module Export ──────────────────────────────────────────────

Export-ModuleMember -Function @(
    'Read-LoomFile',
    'Write-LoomFile',
    'Search-LoomCode',
    'Find-LoomFiles',
    'Get-LoomGitStatus',
    'Get-LoomGitDiff',
    'New-LoomGitCommit',
    'Get-LoomGitLog',
    'Save-LoomGitStash',
    'Restore-LoomGitStash',
    'Get-LoomGpuStatus',
    'Get-LoomDiskUsage',
    'Get-LoomMemoryUsage',
    'Invoke-LoomBuild',
    'Invoke-LoomTest'
)
