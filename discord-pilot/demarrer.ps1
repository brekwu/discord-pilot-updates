# Windows PowerShell 5.1+ : demarrage journalise, sans elevation de privileges.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$projectDir = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $logDir = Join-Path $env:TEMP 'DiscordPilot'
} else {
    $logDir = Join-Path $env:LOCALAPPDATA 'DiscordPilot'
}
New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
$logFile = Join-Path $logDir 'launcher.log'
$transcribing = $false
try {
    # A locked or unavailable transcript must never prevent the app from starting.
    try {
        Start-Transcript -Path $logFile -Force -ErrorAction Stop | Out-Null
        $transcribing = $true
    } catch {
        Write-Host 'Journal PowerShell indisponible : poursuite du lancement.' -ForegroundColor Yellow
    }
    Write-Host "Journal de diagnostic : $logFile" -ForegroundColor Cyan
    Set-Location $projectDir

    $pythonCmd = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $ver = & py -3 -c 'import sys;print(int(sys.version_info >= (3,10)))' 2>$null
        if ($LASTEXITCODE -eq 0 -and ($ver | Out-String).Trim() -eq '1') {
            $pythonCmd = 'py'
        }
    }
    if (-not $pythonCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
        $ver = & python -c 'import sys;print(int(sys.version_info >= (3,10)))' 2>$null
        if ($LASTEXITCODE -eq 0 -and ($ver | Out-String).Trim() -eq '1') {
            $pythonCmd = 'python'
        }
    }
    if (-not $pythonCmd) {
        throw 'Python 3.10+ absent ou non detecte. Installe Python depuis https://www.python.org/downloads/windows/ puis relance.'
    }

    $venvPython = Join-Path $projectDir '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        Write-Host 'Creation de l environnement Python (premier lancement)...'
        if ($pythonCmd -eq 'py') {
            & py -3 -m venv '.venv'
        } else {
            & python -m venv '.venv'
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            throw 'Impossible de creer l environnement Python. Deplace le dossier vers Documents et relance.'
        }
    }

    $reqFile = Join-Path $projectDir 'requirements.txt'
    $reqStamp = Join-Path $projectDir '.venv\pilot-requirements.sha256'
    $reqHash = (Get-FileHash -Path $reqFile -Algorithm SHA256).Hash
    $stampCorrect = (Test-Path $reqStamp) -and ((Get-Content -Path $reqStamp -Raw).Trim() -eq $reqHash)
    & $venvPython -c 'import discord,aiohttp' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $stampCorrect) {
        Write-Host 'Installation des dependances gratuites (une seule fois)...' -ForegroundColor Yellow
        & $venvPython -m pip install -r $reqFile
        if ($LASTEXITCODE -ne 0) {
            throw 'Installation Python echouee. Verifie Internet et le journal de diagnostic.'
        }
        Set-Content -Path $reqStamp -Value $reqHash -NoNewline
    }

    Write-Host 'Application prete. Ouverture de http://127.0.0.1:8765' -ForegroundColor Green
    Write-Host 'Garde cette fenetre ouverte pendant l utilisation.'
    $env:DISCORD_PILOT_LAUNCHER = '1'
    for ($launchCount = 0; $launchCount -lt 4; $launchCount++) {
        & $venvPython (Join-Path $projectDir 'app.py')
        $appCode = $LASTEXITCODE
        if ($appCode -eq 26) {
            # The original browser tab remains open; do not open another tab
            # while the backend briefly restarts on the same local port.
            $env:DISCORD_PILOT_NO_BROWSER = '1'
            $env:DISCORD_PILOT_RESTART_PROBE = '1'
            Write-Host 'Mise a jour verifiee : installation et redemarrage...' -ForegroundColor Cyan
            & $venvPython (Join-Path $projectDir 'updater_cli.py')
            if ($LASTEXITCODE -ne 0) {
                Write-Host 'Mise a jour non installee. Redemarrage de la version precedente...' -ForegroundColor Yellow
                continue
            }
            $newReqHash = (Get-FileHash -Path $reqFile -Algorithm SHA256).Hash
            if ($newReqHash -ne $reqHash) {
                Write-Host 'Nouvelles dependances detectees : mise a jour Python...' -ForegroundColor Cyan
                & $venvPython -m pip install -r $reqFile
                if ($LASTEXITCODE -ne 0) {
                    Write-Host 'Actualisation des dependances echouee. Tentative de redemarrage...' -ForegroundColor Yellow
                } else {
                    Set-Content -Path $reqStamp -Value $newReqHash -NoNewline
                }
            } else {
                Write-Host 'Dependances inchangees : redemarrage sans telechargement.' -ForegroundColor Green
            }
            $reqHash = $newReqHash
            continue
        }
        if ($appCode -ne 0) {
            throw "Discord Pilot s est arrete avec le code $appCode."
        }
        break
    }
    if ($launchCount -ge 4) {
        throw 'Nombre maximal de redemarrages atteint. Relance manuellement.'
    }
} catch {
    Write-Host ''
    Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Journal a transmettre : $logFile" -ForegroundColor Yellow
    exit 1
} finally {
    if ($transcribing) {
        Stop-Transcript | Out-Null
    }
}
