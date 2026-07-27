# Prépare le fichier .env sous Windows — sans avoir besoin de Python.
#
#     powershell -ExecutionPolicy Bypass -File .\scripts\setup-env.ps1
#
# Crée .env depuis .env.example s'il n'existe pas, puis y écrit deux secrets
# tirés du générateur cryptographique de Windows. Rejouer le script laisse
# des secrets déjà renseignés intacts : il ne réécrit que les valeurs par
# défaut ou vides, pour ne pas rendre illisibles des sessions déjà chiffrées.

$ErrorActionPreference = "Stop"

$root    = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$example = Join-Path $root ".env.example"

if (-not (Test-Path $envPath)) {
    Copy-Item $example $envPath
    Write-Host "Fichier .env créé depuis .env.example"
}

# Base64 « url-safe » sans remplissage : le format attendu par l'application.
function New-UrlSafeSecret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$content = Get-Content $envPath -Raw

# JWT_SECRET — remplacé seulement s'il est vide ou resté sur la valeur d'exemple.
if ($content -match '(?m)^JWT_SECRET=\s*$' -or $content -match 'change-me-in-production') {
    $secret  = New-UrlSafeSecret 48
    $content = $content -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$secret"
    Write-Host "JWT_SECRET généré"
} else {
    Write-Host "JWT_SECRET déjà renseigné, laissé tel quel"
}

# ENCRYPTION_KEY — 32 octets exactement, c'est ce que l'application vérifie.
if ($content -match '(?m)^ENCRYPTION_KEY=\s*$') {
    $key     = New-UrlSafeSecret 32
    $content = $content -replace '(?m)^ENCRYPTION_KEY=.*$', "ENCRYPTION_KEY=$key"
    Write-Host "ENCRYPTION_KEY généré"
} else {
    Write-Host "ENCRYPTION_KEY déjà renseigné, laissé tel quel"
}

Set-Content -Path $envPath -Value $content -NoNewline -Encoding UTF8

Write-Host ""
Write-Host "Terminé. Démarrez Docker Desktop, puis :" -ForegroundColor Green
Write-Host "    docker compose up --build"
