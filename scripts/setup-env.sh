#!/usr/bin/env bash
# Prépare le fichier .env — équivalent Linux/macOS de setup-env.ps1.
#
#     bash scripts/setup-env.sh
#
# Rejouer le script laisse des secrets déjà renseignés intacts : il ne
# réécrit que les valeurs par défaut ou vides, pour ne pas rendre illisibles
# des sessions marketplace déjà chiffrées.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$root/.env"

if [ ! -f "$env_file" ]; then
    cp "$root/.env.example" "$env_file"
    echo "Fichier .env créé depuis .env.example"
fi

# Base64 « url-safe » sans remplissage : le format attendu par l'application.
url_safe_secret() {
    openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'
}

replace_line() {
    local key="$1" value="$2"
    # `|` comme séparateur : une clé base64 peut contenir des « / ».
    if [ "$(uname)" = "Darwin" ]; then
        sed -i '' "s|^${key}=.*|${key}=${value}|" "$env_file"
    else
        sed -i "s|^${key}=.*|${key}=${value}|" "$env_file"
    fi
}

if grep -qE '^JWT_SECRET=\s*$' "$env_file" || grep -q 'change-me-in-production' "$env_file"; then
    replace_line JWT_SECRET "$(url_safe_secret 48)"
    echo "JWT_SECRET généré"
else
    echo "JWT_SECRET déjà renseigné, laissé tel quel"
fi

if grep -qE '^ENCRYPTION_KEY=\s*$' "$env_file"; then
    replace_line ENCRYPTION_KEY "$(url_safe_secret 32)"
    echo "ENCRYPTION_KEY généré"
else
    echo "ENCRYPTION_KEY déjà renseigné, laissé tel quel"
fi

echo
echo "Terminé. Démarrez ensuite :"
echo "    docker compose up --build"
