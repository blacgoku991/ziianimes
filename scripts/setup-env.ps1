# Prepare le fichier .env sous Windows, sans avoir besoin de Python.
#
#     powershell -ExecutionPolicy Bypass -File .\scripts\setup-env.ps1
#
# Cree .env depuis .env.example s'il n'existe pas, puis y ecrit deux secrets
# tires du generateur cryptographique de Windows. Rejouer le script laisse
# des secrets deja renseignes intacts : reecrire ENCRYPTION_KEY rendrait
# illisibles toutes les sessions marketplace deja chiffrees.
#
# Les messages sont volontairement sans accent : la console PowerShell par
# defaut n'est pas en UTF-8 et les afficherait en caracteres illisibles.

$ErrorActionPreference = "Stop"

$root    = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$example = Join-Path $root ".env.example"

if (-not (Test-Path $envPath)) {
    Copy-Item $example $envPath
    Write-Host "Fichier .env cree depuis .env.example"
}

# Base64 "url-safe" sans remplissage : le format attendu par l'application.
function New-UrlSafeSecret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$content = Get-Content $envPath -Raw

if ($content -match '(?m)^JWT_SECRET=\s*$' -or $content -match 'change-me-in-production') {
    $content = $content -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$(New-UrlSafeSecret 48)"
    Write-Host "JWT_SECRET genere"
} else {
    Write-Host "JWT_SECRET deja renseigne, laisse tel quel"
}

# ENCRYPTION_KEY : 32 octets exactement, c'est ce que l'application verifie.
if ($content -match '(?m)^ENCRYPTION_KEY=\s*$') {
    $content = $content -replace '(?m)^ENCRYPTION_KEY=.*$', "ENCRYPTION_KEY=$(New-UrlSafeSecret 32)"
    Write-Host "ENCRYPTION_KEY genere"
} else {
    Write-Host "ENCRYPTION_KEY deja renseigne, laisse tel quel"
}

# Ecriture SANS marque d'ordre d'octets. `Set-Content -Encoding UTF8` en
# ajoute une sous Windows PowerShell 5.1, et un .env qui commence par un BOM
# n'est pas lu de la meme facon par tous les analyseurs.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($envPath, $content, $utf8NoBom)

# Un .env ecrit precedemment avec un BOM est repare au passage.
$bytes = [System.IO.File]::ReadAllBytes($envPath)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [System.IO.File]::WriteAllBytes($envPath, $bytes[3..($bytes.Length - 1)])
    Write-Host "Marque d'ordre d'octets retiree du fichier .env"
}

Write-Host ""

# Verification de Docker : c'est le blocage le plus frequent a cette etape.
# `docker info` ecrit sur la sortie d'erreur quand le moteur est arrete ;
# avec $ErrorActionPreference = "Stop", cela suffirait a interrompre le
# script. On neutralise donc la preference le temps du controle.
$dockerOk = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $null = & docker info 2>&1
    $dockerOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previousPreference
}

if ($dockerOk) {
    Write-Host "Docker repond. Vous pouvez lancer :" -ForegroundColor Green
    Write-Host "    docker compose up --build db redis api frontend"
} else {
    Write-Host "Fichier .env pret, mais Docker ne repond pas." -ForegroundColor Yellow
    Write-Host ""
    $desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Write-Host "Docker Desktop est installe mais n'est pas demarre. Lancez-le :"
        Write-Host "    Start-Process '$desktop'"
        Write-Host "Attendez que l'icone baleine soit stable, puis relancez ce script."
    } else {
        Write-Host "Docker Desktop ne semble pas installe."
        Write-Host "Telechargez-le sur https://www.docker.com/products/docker-desktop/"
        Write-Host "puis redemarrez la machine avant de reessayer."
    }
}
