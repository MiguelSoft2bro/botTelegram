#!/bin/bash
# OpenCode Telegram Bridge — Interactive Installer (arrow-key navigation)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALLER_VERSION="$(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo "dev")"
ASCII_ART='  .;;,.   
 .cooodo:. 
.:oxkxxkxo;.
 ;dKKKKKOd; 
  ,okOkd,   
    ...     '
COLOR_TITLE="\033[95m"
COLOR_MENU="\033[96m"
COLOR_HIGHLIGHT="\033[7m"
COLOR_RESET="\033[0m"

cleanup() {
    tput cnorm 2>/dev/null || true
}

trap cleanup EXIT

show_header() {
    clear
    echo -e "${COLOR_TITLE}OpenCode Telegram Bridge Installer v${INSTALLER_VERSION}${COLOR_RESET}"
    echo "=========================================="
    echo "$ASCII_ART"
    echo ""
}

pause() {
    echo ""
    read -rp "Pulsa Enter para volver al menú..." _
}

prompt_value() {
    local label="$1"
    local allow_empty="$2"
    while true; do
        read -rp "$label" value
        if [ "$value" = "0" ]; then
            echo "__BACK__"
            return
        fi
        if [ -z "$value" ] && [ "$allow_empty" != "true" ]; then
            echo "El valor no puede estar vacío. Introduce 0 para volver."
        else
            echo "$value"
            return
        fi
    done
}

check_prereqs() {
    show_header
    echo "Comprobando requisitos básicos..."
    local missing=false
    if ! command -v python3 >/dev/null; then
        echo "❌ Python 3 no encontrado"
        missing=true
    else
        echo "✅ Python 3"
    fi
    if ! command -v pip3 >/dev/null; then
        echo "❌ pip3 no encontrado"
        missing=true
    else
        echo "✅ pip3"
    fi
    if ! command -v ffmpeg >/dev/null; then
        echo "⚠️  ffmpeg no instalado (requerido para notas de voz)"
    else
        echo "✅ ffmpeg"
    fi
    if [ "$missing" = true ]; then
        echo "Instala los binarios marcados y vuelve a ejecutar el instalador."
        exit 1
    fi
    pause
}

install_dependencies() {
    show_header
    echo "Instalando dependencias de Python..."
    pip3 install -r "$PROJECT_DIR/requirements.txt"
    echo "✅ Dependencias instaladas"
    pause
}

configure_env() {
    show_header
    echo "Configuración de credenciales (.env)"
    echo "Introduce 0 en cualquier campo para volver al menú."
    if [ -f "$PROJECT_DIR/.env" ]; then
        read -rp "Ya existe .env. ¿Quieres sobrescribirlo? [y/N]: " answer
        case "$answer" in
            y|Y) ;;
            *) echo "Manteniendo .env actual"; pause; return ;;
        esac
    fi

    echo "Necesitas tu propio bot de Telegram (creado con @BotFather)."
    bot_token=$(prompt_value "BOT_TOKEN: " false)
    [ "$bot_token" = "__BACK__" ] && return
    user_id=$(prompt_value "Tu User ID (de @userinfobot): " false)
    [ "$user_id" = "__BACK__" ] && return
    group_id=$(prompt_value "ID de grupo para notificaciones (0 para omitir): " true)
    [ "$group_id" = "__BACK__" ] && return
    whisper_model=$(prompt_value "Modelo de Whisper [base]: " true)
    [ "$whisper_model" = "__BACK__" ] && return
    whisper_model=${whisper_model:-base}

    cat > "$PROJECT_DIR/.env" <<EOF
BOT_TOKEN=$bot_token
ALLOWED_USER_IDS=$user_id
NOTIFICATION_GROUP_ID=${group_id:-0}
WHISPER_MODEL=${whisper_model}
EOF

    echo "✅ Archivo .env generado"
    pause
}

configure_shell_function() {
    show_header
    echo "Configurando la función opencode()..."
    echo "Introduce 0 en cualquier confirmación para cancelar."
    read -rp "¿Quieres añadir/configurar la función ahora? (y/N, 0 para volver): " desire
    case "$desire" in
        0|n|N|"") echo "Operación cancelada"; sleep 1; return ;;
        y|Y) ;;
        *) echo "Opción inválida, cancelando"; sleep 1; return ;;
    esac
    local shell_config=""
    if [ -f "$HOME/.zshrc" ]; then
        shell_config="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        shell_config="$HOME/.bashrc"
    else
        echo "No se encontró .zshrc ni .bashrc. Configura tu shell manualmente."
        pause
        return
    fi

    if grep -q "OpenCode Telegram Bridge" "$shell_config"; then
        read -rp "La función ya existe en $shell_config. ¿Reemplazar? [y/N]: " resp
        case "$resp" in
            0) return ;;
            y|Y) ;;
            *) echo "Manteniendo configuración actual"; pause; return ;;
        esac
    fi

    cat >> "$shell_config" <<EOF

# OpenCode Telegram Bridge helpers
BRIDGE_HOME="$PROJECT_DIR"

opencode() {
    local port=4096
    while lsof -i :\$port &>/dev/null; do
        ((port++))
    done

    if ! pgrep -f "python3.*bridge.py" >/dev/null; then
        echo "Arrancando Telegram bridge..."
        (
            cd "\$BRIDGE_HOME" &&
            nohup python3 bridge.py >/tmp/bridge.log 2>&1 &
        )
    else
        echo "Telegram bridge ya estaba activo"
    fi

    echo "OpenCode starting on port \$port"
    command opencode --port \$port "\$@"

    if ! pgrep -f "opencode --port" >/dev/null && pgrep -f "python3.*bridge.py" >/dev/null; then
        echo "Cerrando Telegram bridge (no quedan sesiones de OpenCode)"
        pkill -f "python3.*bridge.py"
    fi
}
EOF

    echo "✅ Función añadida a $shell_config"
    echo "Ejecuta: source $shell_config"
    pause
}

install_skill() {
    show_header
    echo "Instalando skill de OpenCode..."
    local skill_dir="$HOME/.config/opencode/skills/telegram-bridge"
    mkdir -p "$skill_dir"
    local bridge_path="$PROJECT_DIR/bridge.py"

    cat > "$skill_dir/SKILL.md" <<EOF
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

1. **Check Prerequisites**
   ```bash
   curl -s http://localhost:4096/session || echo "OpenCode not running on port 4096"
   ```
2. **Start the Bot**
   ```bash
   pkill -0 -f "python3.*bridge.py" 2>/dev/null && echo "Bot already running" || python3 ${bridge_path} &
   ```
3. **Get Session ID**
   ```bash
   for port in {4096..4106}; do
     if curl -s "http://localhost:\$port/session" &>/dev/null; then
       echo "Port \$port: \$(curl -s http://localhost:\$port/session | jq -r '.[0].id')"
     fi
   done
   ```
4. **Tell User**
   - Bot is running
   - Tell them to open Telegram and use /start
   - Click a button to connect
EOF

    echo "✅ Skill instalada en $skill_dir"
    pause
}

full_install() {
    show_header
    echo "Modo instalación completa"
    read -rp "¿Quieres continuar? (y/N, 0 para cancelar): " confirm
    case "$confirm" in
        0|n|N|"" ) echo "Operación cancelada"; sleep 1; return ;;
        y|Y ) ;;
        * ) echo "Opción inválida, cancelando"; sleep 1; return ;;
    esac

    check_prereqs
    install_dependencies
    configure_env
    configure_shell_function
    install_skill
    show_header
    echo "🎉 Instalación completada"
    echo "1. Abre una terminal nueva o ejecuta: source ~/.zshrc"
    echo "2. Lanza 'opencode' y el puente se iniciará solo"
    pause
}

run_action() {
    case "$1" in
        1) full_install ;;
        2) configure_env ;;
        3) configure_shell_function ;;
        4) install_skill ;;
        5) install_dependencies ;;
        6) show_header; echo "Saliendo..."; exit 0 ;;
        *) echo "Opción inválida" ;;
    esac
}

menu() {
    while true; do
        show_header
        cat <<EOF
1. Instalación completa
2. Solo generar/actualizar .env
3. Solo configurar función opencode()
4. Instalar skill de OpenCode
5. Instalar dependencias
6. Salir

Introduce el número de la opción (1-6) o Q para salir:
EOF
        read -rp "> " choice
        case "$choice" in
            q|Q) show_header; echo "Saliendo..."; exit 0 ;;
            1|2|3|4|5|6) run_action "$choice" ;;
            *) echo "Opción inválida"; sleep 1 ;;
        esac
    done
}

menu
