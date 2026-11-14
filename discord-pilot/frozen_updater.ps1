# Windows-only updater. Started BEFORE the HTTP server exits; it replaces the
# one-file PyInstaller executable only after the bootloader has released it.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$PendingPath,
    [Parameter(Mandatory=$true)][string]$ExpectedHash,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [Parameter(Mandatory=$true)][int]$ParentPid,
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$Port,
    [Parameter(Mandatory=$true)][string]$TargetVersion
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $DataRoot 'updater.log'
$backup = $null
$swapped = $false
$newProcess = $null

function Write-UpdateLog([string]$Message) {
    try { Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) $Message" -ErrorAction Stop } catch {}
}

function Get-ExecutableHash([string]$FilePath) {
    # Works in Windows PowerShell 5.1 even when PSModulePath makes
    # Get-FileHash / Microsoft.PowerShell.Utility unavailable.
    $stream = [System.IO.File]::Open(
        $FilePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
        finally { $sha.Dispose() }
    } finally { $stream.Dispose() }
}

function Get-RunningServerVersion {
    # Avoid Invoke-RestMethod: its Windows PowerShell module can be unavailable
    # when the EXE inherits a PowerShell 7 PSModulePath from another launcher.
    $request = [System.Net.WebRequest]::Create("http://127.0.0.1:$Port/api/bootstrap")
    $request.Timeout = 1800
    $request.Proxy = $null
    $response = $request.GetResponse()
    try {
        $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
        try { $body = $reader.ReadToEnd() }
        finally { $reader.Dispose() }
        if ($body -match '"version"\s*:\s*"([0-9]+\.[0-9]+\.[0-9]+)"') {
            return $Matches[1]
        }
    } finally { $response.Dispose() }
    return $null
}

function Start-DiscordPilot {
    # Keep the port stable so the original tab can poll /api/bootstrap and refresh.
    $env:DISCORD_PILOT_PORT = [string]$Port
    $env:DISCORD_PILOT_NO_BROWSER = '1'
    $child = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru -ErrorAction Stop
    Write-UpdateLog "EXE relance; PID=$($child.Id), port=$Port"
    return $child
}

try {
    Write-UpdateLog "Debut de mise a jour; PID precedent=$ParentPid, port=$Port"
    if (-not ($ExpectedHash -match '^[a-fA-F0-9]{64}$')) { throw 'Empreinte SHA-256 incorrecte.' }
    if (-not ($TargetVersion -match '^\d{1,3}\.\d{1,3}\.\d{1,3}$')) { throw 'Version cible incorrecte.' }
    if (-not (Test-Path -LiteralPath $PendingPath -PathType Leaf)) { throw 'EXE telecharge introuvable.' }
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { throw 'EXE actuellement installe introuvable.' }
    $realHash = Get-ExecutableHash $PendingPath
    if ($realHash -ne $ExpectedHash) { throw 'Empreinte du programme non conforme.' }

    # PyInstaller --onefile sometimes keeps its parent bootloader alive after
    # Python exits. Wait for that process, then allow time for Windows locks.
    $ended = $false
    for ($i = 0; $i -lt 240; $i++) {
        if (-not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) { $ended = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ended) { throw 'Discord Pilot ne s est pas arrete dans les 120 secondes.' }
    Start-Sleep -Milliseconds 1500

    $backupDir = Join-Path (Join-Path $DataRoot 'updates') 'backups'
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $backupDir ("DiscordPilot-$stamp-" + [Guid]::NewGuid().ToString('N').Substring(0,6) + '.exe')
    Copy-Item -LiteralPath $ExePath -Destination $backup -ErrorAction Stop

    for ($attempt = 1; $attempt -le 120; $attempt++) {
        try {
            Copy-Item -LiteralPath $PendingPath -Destination $ExePath -Force -ErrorAction Stop
            $swapped = $true
            break
        } catch {
            if ($attempt -eq 120) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $swapped) { throw 'Remplacement du programme impossible.' }
    if ((Get-ExecutableHash $ExePath) -ne $ExpectedHash) {
        throw 'Le programme installe ne correspond pas au telechargement verifie.'
    }

    $newProcess = Start-DiscordPilot
    $ready = $false
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        try {
            $runningVersion = Get-RunningServerVersion
            if ($runningVersion -eq $TargetVersion) { $ready = $true; break }
        } catch {}
        $newProcess.Refresh()
        if ($newProcess.HasExited) { throw 'Le nouvel EXE s est arrete avant de demarrer son serveur.' }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Le nouvel EXE ne repond pas sur le port attendu.' }

    Remove-Item -LiteralPath $PendingPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path (Join-Path $DataRoot 'updates') 'pending.json') -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "Version $TargetVersion installee et ouverte; sauvegarde : $backup"
} catch {
    Write-UpdateLog "ERREUR : $($_.Exception.Message)"
    # Keep the downloaded update and backup if anything goes wrong.
    if ($swapped -and $backup -and (Test-Path -LiteralPath $backup -PathType Leaf)) {
        try {
            if ($newProcess) {
                $newProcess.Refresh()
                if (-not $newProcess.HasExited) {
                    Stop-Process -Id $newProcess.Id -Force -ErrorAction Stop
                    Start-Sleep -Seconds 2
                }
            }
            Copy-Item -LiteralPath $backup -Destination $ExePath -Force -ErrorAction Stop
            Write-UpdateLog 'Version precedente restauree apres echec du redemarrage.'
        } catch {
            Write-UpdateLog "Impossible de restaurer automatiquement : $($_.Exception.Message)"
        }
    }
    try { Start-DiscordPilot | Out-Null } catch {
        Write-UpdateLog "Impossible de relancer le programme : $($_.Exception.Message)"
    }
    exit 1
}
