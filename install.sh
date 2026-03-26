#!/bin/bash
# OpenCode Telegram Bridge - Installation Script

set -e

echo "OpenCode Telegram Bridge - Instalacion"
echo "=========================================="
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 no encontrado. Instalalo primero."
    exit 1
fi
echo "OK: Python 3 encontrado"

# Check pip3
if ! command -v pip3 &> /dev/null; then
    echo "ERROR: pip3 no encontrado. Instalalo primero."
    exit 1
fi
echo "OK: pip3 encontrado"

# Install dependencies
echo ""
echo "Instalando dependencias..."
pip3 install -r requirements.txt

# Create .env if not exists
if [ ! -f .env ]; then
    echo ""
    echo "Configuracion del bot"
    echo "------------------------"
    echo ""
    echo "=== PASO 1: Crear tu bot en Telegram ==="
    echo ""
    echo "1. Abre Telegram y busca @BotFather"
    echo "2. Envia /newbot"
    echo "3. Elige un NOMBRE para tu bot (ej: 'Mi OpenCode Bot')"
    echo "4. Elige un USERNAME (debe terminar en 'bot', ej: 'mi_opencode_bot')"
    echo "5. BotFather te dara un token como: 123456789:ABCdefGHI..."
    echo ""
    read -p "Pega tu BOT_TOKEN: " bot_token
    
    if [ -z "$bot_token" ]; then
        echo "ERROR: El token no puede estar vacio"
        exit 1
    fi
    
    echo ""
    echo "=== PASO 2: Obtener tu User ID ==="
    echo ""
    echo "1. Busca @userinfobot en Telegram"
    echo "2. Envia /start"
    echo "3. Copia el numero de 'Id' (ej: 429591886)"
    echo ""
    echo "IMPORTANTE: Solo este ID podra usar tu bot (seguridad)"
    echo ""
    read -p "Tu User ID: " user_id
    
    if [ -z "$user_id" ]; then
        echo "ERROR: El User ID no puede estar vacio"
        exit 1
    fi
    echo ""
    echo "=== PASO 3 (opcional): Grupo de notificaciones ==="
    echo ""
    echo "Puedes crear un grupo para recibir notificaciones push."
    echo "Si no quieres, pulsa Enter para saltar."
    echo ""
    read -p "ID del grupo (Enter para saltar): " group_id
    
    # Create .env
    cat > .env << EOF
BOT_TOKEN=${bot_token}
ALLOWED_USER_IDS=${user_id}
OPENCODE_PORT=4096
NOTIFICATION_GROUP_ID=${group_id:-0}
EOF
    echo "OK: Archivo .env creado"
else
    echo "OK: Archivo .env ya existe"
fi

# Add function to shell config
echo ""
echo "Configurando shell..."

SHELL_CONFIG=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
fi

if [ -n "$SHELL_CONFIG" ]; then
    # Check if already configured
    if grep -q "opencode()" "$SHELL_CONFIG"; then
        echo "OK: Funcion opencode() ya configurada en $SHELL_CONFIG"
    else
        cat >> "$SHELL_CONFIG" << 'EOF'

# OpenCode with dynamic port assignment
opencode() {
    local port=4096
    while lsof -i :$port &>/dev/null; do
        ((port++))
    done
    echo "OpenCode starting on port $port"
    command opencode --port $port "$@"
}
EOF
        echo "OK: Funcion opencode() anadida a $SHELL_CONFIG"
        echo "   Ejecuta: source $SHELL_CONFIG"
    fi
fi

# Create skill directory
SKILL_DIR="$HOME/.config/opencode/skills/telegram-bridge"
mkdir -p "$SKILL_DIR"

# Get the absolute path of bridge.py
BRIDGE_PATH="$(cd "$(dirname "$0")" && pwd)/bridge.py"

# Copy/create skill
cat > "$SKILL_DIR/SKILL.md" << EOF
---
name: telegram-bridge
description: >
  Start Telegram bridge bot and provide session connection instructions.
  Trigger: When user says "arranca el bot", "start the bot", "telegram", "conectar telegram".
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "2.0"
---

## When to Use

- User says "arranca el bot", "start the bot", "telegram", "conectar telegram"
- User wants to control OpenCode from their phone

## What to Do

### 1. Check Prerequisites

\`\`\`bash
# Verify OpenCode is running with HTTP API
curl -s http://localhost:4096/session || echo "OpenCode not running on port 4096"
\`\`\`

### 2. Start the Bot

\`\`\`bash
# Check if already running
pkill -0 -f "python3.*bridge.py" 2>/dev/null && echo "Bot already running" || python3 ${BRIDGE_PATH} &
\`\`\`

### 3. Get Session ID

\`\`\`bash
# Scan active ports
for port in {4096..4106}; do
  if curl -s "http://localhost:\$port/session" &>/dev/null; then
    echo "Port \$port: \$(curl -s http://localhost:\$port/session | jq -r '.[0].id')"
  fi
done
\`\`\`

### 4. Tell User

Respond with:
- Bot is running
- Tell them to open Telegram and use /start to see active sessions
- Click a button to connect
EOF

echo "OK: Skill instalado en $SKILL_DIR"

echo ""
echo "=========================================="
echo "Instalacion completada!"
echo ""
echo "Proximos pasos:"
if [ -n "$SHELL_CONFIG" ]; then
    echo "1. source $SHELL_CONFIG"
else
    echo "1. Configura tu shell manualmente"
fi
echo "2. Inicia OpenCode: opencode"
echo "3. En otra terminal: python3 bridge.py"
echo "4. En Telegram: /start en tu bot"
echo ""
echo "O simplemente dile a OpenCode: 'arranca el bot'"
echo "=========================================="
