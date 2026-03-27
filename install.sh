#!/bin/bash
# OpenCode Telegram Bridge — Interactive Installer (arrow-key navigation)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
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
    echo -e "${COLOR_TITLE}OpenCode Telegram Bridge Installer${COLOR_RESET}"
    echo "=========================================="
    echo "$ASCII_ART"
    echo ""
}

pause() {
    echo ""
    read -rp "Pulsa Enter para volver al menú..." _
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
    if [ -f "$PROJECT_DIR/.env" ]; then
        read -rp "Ya existe .env. ¿Quieres sobrescribirlo? [y/N]: " answer
        case "$answer" in
            y|Y) ;;
            *) echo "Manteniendo .env actual"; pause; return ;;
        esac
    fi

    echo "Necesitas tu propio bot de Telegram (creado con @BotFather)."
    read -rp "BOT_TOKEN: " bot_token
    if [ -z "$bot_token" ]; then
        echo "El token no puede estar vacío."; pause; return
    fi
    read -rp "Tu User ID (de @userinfobot): " user_id
    if [ -z "$user_id" ]; then
        echo "El User ID no puede estar vacío."; pause; return
    fi
    read -rp "ID de grupo para notificaciones (Enter para omitir): " group_id
    read -rp "Modelo de Whisper [base]: " whisper_model

    cat > "$PROJECT_DIR/.env" <<EOF
BOT_TOKEN=$bot_token
ALLOWED_USER_IDS=$user_id
NOTIFICATION_GROUP_ID=${group_id:-0}
WHISPER_MODEL=${whisper_model:-base}
EOF

    echo "✅ Archivo .env generado"
    pause
}

configure_shell_function() {
    show_header
    echo "Configurando la función opencode()..."
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
        echo "La función ya existe en $shell_config"
        pause
        return
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
        0) full_install ;;
        1) configure_env ;;
        2) configure_shell_function ;;
        3) install_skill ;;
        4) install_dependencies ;;
        5) show_header; echo "Saliendo..."; exit 0 ;;
    esac
}

menu() {
    local options=(
        "Instalación completa"
        "Solo generar/actualizar .env"
        "Solo configurar función opencode()"
        "Instalar skill de OpenCode"
        "Instalar dependencias"
        "Salir"
    )
    local selected=0
    tput civis 2>/dev/null || true
    while true; do
        show_header
        echo "Usa ↑/↓ o números (1-${#options[@]}) para elegir opción. Enter ejecuta. Q para salir."
        echo ""
        printf "+--------------------------------------+\n"
        for i in "${!options[@]}"; do
            local idx=$((i+1))
            local label="${idx}. ${options[i]}"
            if [ "$i" -eq "$selected" ]; then
                printf "| ${COLOR_HIGHLIGHT}%-36s${COLOR_RESET} |\n" "$label"
            else
                printf "| %-36s |\n" "$label"
            fi
        done
        printf "+--------------------------------------+\n"

        read -rsn1 key 2>/dev/null || key=""

        # Arrow keys
        if [[ $key == $'\x1b' ]]; then
            read -rsn2 -t 0.001 key2 || true
            case "$key2" in
                "[A") selected=$(( (selected - 1 + ${#options[@]}) % ${#options[@]} )) ; continue ;;
                "[B") selected=$(( (selected + 1) % ${#options[@]} )) ; continue ;;
            esac
        fi

        case "$key" in
            q|Q)
                show_header
                echo "Saliendo..."
                exit 0
                ;;
            $'\n')
                run_action "$selected"
                ;;
            [1-9])
                local choice=$((key-1))
                if [ "$choice" -ge 0 ] && [ "$choice" -lt "${#options[@]}" ]; then
                    run_action "$choice"
                fi
                ;;
            *)
                # fallback para entradas largas
                read -rp $'\nEscribe número de opción: ' typed
                if [[ "$typed" =~ ^[0-9]+$ ]]; then
                    local idx=$((typed-1))
                    if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#options[@]}" ]; then
                        run_action "$idx"
                    fi
                fi
                ;;
        esac
    done
}

menu
