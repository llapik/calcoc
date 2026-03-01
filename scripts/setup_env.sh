#!/usr/bin/env bash
# Set up local development environment for AI PC Repair & Optimizer.
#
# Usage: bash scripts/setup_env.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Setting up development environment ==="

cd "$PROJECT_DIR"

# Check Python version
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ is required."
    exit 1
fi

echo "Using: $($PYTHON --version)"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
fi

source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install dev dependencies
pip install pytest flake8

# Create local data directories
mkdir -p data/knowledge

# Create sample knowledge base
if [ ! -f "data/knowledge/common_fixes.json" ]; then
    cat > data/knowledge/common_fixes.json << 'EOF'
{
  "entries": [
    {
      "title": "Windows не загружается — чёрный экран",
      "category": "bootloader",
      "content": "Частые причины: повреждённый загрузчик BCD, ошибка обновления Windows, повреждение файловой системы. Решение: 1) Проверить S.M.A.R.T. диска. 2) Запустить fsck/chkdsk. 3) Восстановить BCD через bootrec /rebuildbcd. 4) Последнее средство — переустановка."
    },
    {
      "title": "Компьютер зависает или перезагружается",
      "category": "hardware",
      "content": "Возможные причины: перегрев CPU/GPU, неисправная ОЗУ, проблемы с блоком питания, ошибки на диске. Диагностика: 1) Проверить температуры (sensors). 2) Тест ОЗУ (memtest86). 3) Проверка S.M.A.R.T. 4) Проверка логов (dmesg, syslog)."
    },
    {
      "title": "Медленная работа компьютера",
      "category": "performance",
      "content": "Типичные причины: HDD вместо SSD, мало ОЗУ (<8 ГБ), вирусы, фрагментация, автозагрузка. Решение: 1) Замена HDD на SSD (максимальный эффект). 2) Добавление ОЗУ. 3) Очистка автозагрузки. 4) Проверка на вирусы. 5) Очистка временных файлов."
    },
    {
      "title": "Синий экран смерти (BSOD)",
      "category": "software",
      "content": "Анализ: 1) Код ошибки из minidump. 2) IRQL_NOT_LESS_OR_EQUAL — часто драйверы. 3) KERNEL_DATA_INPAGE_ERROR — проблемы с диском. 4) PAGE_FAULT_IN_NONPAGED_AREA — возможно неисправность ОЗУ. 5) Проверить целостность sfc /scannow."
    },
    {
      "title": "Нет звука",
      "category": "drivers",
      "content": "Проверить: 1) Драйвер аудио (lspci | grep Audio). 2) PulseAudio/ALSA статус. 3) Для Windows — служба Windows Audio. 4) Физическое подключение колонок/наушников. 5) Обновить драйверы."
    }
  ]
}
EOF
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Activate the environment:  source .venv/bin/activate"
echo "Run the application:       python -m src.core.app"
echo "Run tests:                 pytest tests/ -v"
echo "Web UI will be at:         http://127.0.0.1:8080"
