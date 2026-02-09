#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Helper: prompt for a value with optional default
ask() {
    local var_name="$1"
    local prompt="$2"
    local default="$3"
    local value
    if [ -n "$default" ]; then
        read -rp "  $prompt [$default]: " value
        value="${value:-$default}"
    else
        read -rp "  $prompt: " value
    fi
    eval "$var_name=\"$value\""
}

# Interactive setup when .env doesn't exist
if [ ! -f .env ]; then
    echo ""
    echo -e "${CYAN}${BOLD}========================================${NC}"
    echo -e "${CYAN}${BOLD}  Deye Dashboard — Local Setup${NC}"
    echo -e "${CYAN}${BOLD}========================================${NC}"
    echo ""
    echo "No .env file found. Let's configure your dashboard."
    echo "Press Enter to accept defaults shown in [brackets]."
    echo ""

    # --- Inverter (auto-discover or manual) ---
    echo -e "${YELLOW}Inverter Settings${NC}"

    # Ensure dependencies are available for discovery
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -q pysolarmanv5 2>/dev/null

    echo "  Scanning local network for Deye/Solarman inverters..."
    echo ""
    DISCOVER_JSON=$(python3 discover_inverter.py --json 2>/dev/null || echo "[]")
    DISCOVER_COUNT=$(echo "$DISCOVER_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [ "$DISCOVER_COUNT" -gt 0 ]; then
        echo -e "  ${GREEN}Found ${DISCOVER_COUNT} device(s) with port 8899 open:${NC}"
        echo ""
        # Display each discovered device
        for i in $(seq 0 $((DISCOVER_COUNT - 1))); do
            DEV_IP=$(echo "$DISCOVER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin)[$i]; print(d['ip'])")
            DEV_MODEL=$(echo "$DISCOVER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin)[$i]; print(d.get('model') or 'Unknown')")
            echo -e "    ${CYAN}[$((i + 1))]${NC} IP: ${BOLD}${DEV_IP}${NC}  |  Model: ${DEV_MODEL}"
        done
        echo -e "    ${CYAN}[$((DISCOVER_COUNT + 1))]${NC} Enter manually"
        echo ""

        read -rp "  Select device [1]: " DEV_CHOICE
        DEV_CHOICE="${DEV_CHOICE:-1}"

        if [ "$DEV_CHOICE" -le "$DISCOVER_COUNT" ] 2>/dev/null; then
            IDX=$((DEV_CHOICE - 1))
            INVERTER_IP=$(echo "$DISCOVER_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin)[$IDX]; print(d['ip'])")
            echo -e "  ${GREEN}Selected: ${INVERTER_IP}${NC}"
            echo ""
            ask LOGGER_SERIAL "Logger serial number" ""
        else
            ask INVERTER_IP "Inverter IP address" ""
            ask LOGGER_SERIAL "Logger serial number" ""
        fi
    else
        echo -e "  ${YELLOW}No inverters found on the local network.${NC}"
        echo "  You can enter the details manually."
        echo ""
        ask INVERTER_IP "Inverter IP address" ""
        ask LOGGER_SERIAL "Logger serial number" ""
    fi
    echo ""

    # --- Weather ---
    echo -e "${YELLOW}Weather Settings (Open-Meteo API)${NC}"
    ask WEATHER_LATITUDE "Latitude" "50.4501"
    ask WEATHER_LONGITUDE "Longitude" "30.5234"
    echo ""

    # --- Outage Provider ---
    echo -e "${YELLOW}Outage Schedule Provider${NC}"
    echo "  1) lvivoblenergo"
    echo "  2) yasno"
    echo "  3) none (disable)"
    read -rp "  Choose [1]: " OUTAGE_CHOICE
    OUTAGE_CHOICE="${OUTAGE_CHOICE:-1}"

    case "$OUTAGE_CHOICE" in
        1)
            OUTAGE_PROVIDER="lvivoblenergo"
            ask OUTAGE_GROUP "Outage group (e.g. 1.1)" "1.1"
            ;;
        2)
            OUTAGE_PROVIDER="yasno"
            ask OUTAGE_REGION_ID "YASNO region ID (e.g. 25 = Kyiv)" "25"
            ask OUTAGE_DSO_ID "YASNO DSO ID (e.g. 902 = DTEK Kyiv)" "902"
            ask OUTAGE_GROUP "Queue/group number (e.g. 2.1)" "2.1"
            ;;
        3)
            OUTAGE_PROVIDER="none"
            ;;
        *)
            echo -e "${RED}Invalid choice, defaulting to lvivoblenergo${NC}"
            OUTAGE_PROVIDER="lvivoblenergo"
            ask OUTAGE_GROUP "Outage group (e.g. 1.1)" "1.1"
            ;;
    esac
    echo ""

    # --- Write .env ---
    echo -e "${YELLOW}Writing .env file...${NC}"
    cat > .env << EOF
# Deye Inverter Configuration
INVERTER_IP=${INVERTER_IP}
LOGGER_SERIAL=${LOGGER_SERIAL}

# Weather (coordinates for Open-Meteo API)
WEATHER_LATITUDE=${WEATHER_LATITUDE}
WEATHER_LONGITUDE=${WEATHER_LONGITUDE}

# Outage Schedule Provider
OUTAGE_PROVIDER=${OUTAGE_PROVIDER}
EOF

    # Add provider-specific vars
    if [ "$OUTAGE_PROVIDER" = "yasno" ]; then
        cat >> .env << EOF
OUTAGE_REGION_ID=${OUTAGE_REGION_ID}
OUTAGE_DSO_ID=${OUTAGE_DSO_ID}
OUTAGE_GROUP=${OUTAGE_GROUP}
EOF
    elif [ "$OUTAGE_PROVIDER" = "lvivoblenergo" ]; then
        cat >> .env << EOF
OUTAGE_GROUP=${OUTAGE_GROUP}
EOF
    fi

    cat >> .env << EOF

# Telegram Bot (disabled for local development)
TELEGRAM_ENABLED=false
EOF

    echo -e "${GREEN}.env file created successfully!${NC}"
    echo ""
fi

# Load .env but disable Telegram bot for local development
set -a
source .env
set +a
export TELEGRAM_ENABLED=false

# Validate required vars
MISSING=()
[ -z "${INVERTER_IP:-}" ] && MISSING+=("INVERTER_IP")
[ -z "${LOGGER_SERIAL:-}" ] && MISSING+=("LOGGER_SERIAL")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required environment variables:${NC}"
    for var in "${MISSING[@]}"; do
        echo "  - $var"
    done
    echo ""
    echo "Set them in your .env file or run this script again to regenerate it."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q -r requirements.txt

echo -e "${GREEN}Starting Deye Dashboard locally (Telegram bot disabled)...${NC}"
python3 app.py
