#!/usr/bin/env bash
# Build a bootable ISO image for AI PC Repair & Optimizer.
#
# Prerequisites: debootstrap, squashfs-tools, grub-pc-bin, grub-efi-amd64-bin,
#                xorriso, mtools, python3
#
# Usage: bash scripts/build_iso.sh [output.iso]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${PROJECT_DIR}/build"
ROOTFS="${BUILD_DIR}/rootfs"
ISO_DIR="${BUILD_DIR}/iso"
OUTPUT="${1:-${PROJECT_DIR}/calcoc.iso}"

echo "=== AI PC Repair & Optimizer — ISO Builder ==="
echo "Project dir: ${PROJECT_DIR}"
echo "Output: ${OUTPUT}"

# Cleanup from previous builds
rm -rf "${BUILD_DIR}"
mkdir -p "${ROOTFS}" "${ISO_DIR}/boot/grub"

# ---------------------------------------------------------------
# Step 1: Create minimal root filesystem (Alpine-based)
# ---------------------------------------------------------------
echo "[1/6] Creating root filesystem..."

if command -v debootstrap &>/dev/null; then
    debootstrap --variant=minbase --include=\
python3,python3-pip,python3-venv,\
smartmontools,pciutils,usbutils,dmidecode,\
ntfs-3g,dosfstools,e2fsprogs,\
clamav,clamav-freshclam,\
lighttpd,\
hdparm,lm-sensors,ethtool,\
grub-pc-bin,grub-efi-amd64-bin \
        bookworm "${ROOTFS}" http://deb.debian.org/debian
else
    echo "WARNING: debootstrap not found. Creating skeleton rootfs."
    mkdir -p "${ROOTFS}"/{bin,sbin,etc,proc,sys,dev,tmp,usr/bin,usr/sbin,var/log,opt/calcoc}
fi

# ---------------------------------------------------------------
# Step 2: Install application
# ---------------------------------------------------------------
echo "[2/6] Installing application..."

APP_DIR="${ROOTFS}/opt/calcoc"
mkdir -p "${APP_DIR}"
cp -r "${PROJECT_DIR}/src" "${APP_DIR}/src"
cp -r "${PROJECT_DIR}/config" "${APP_DIR}/config"
cp -r "${PROJECT_DIR}/data" "${APP_DIR}/data"
cp "${PROJECT_DIR}/requirements.txt" "${APP_DIR}/"

# Create startup script
cat > "${ROOTFS}/opt/calcoc/start.sh" << 'STARTUP'
#!/bin/bash
# AI PC Repair & Optimizer — Boot startup script

export PYTHONPATH=/opt/calcoc
export HOME=/root

# Parse kernel command line
NOAI=false
EXPERT=false
ROLLBACK=false

for arg in $(cat /proc/cmdline); do
    case "$arg" in
        noai) NOAI=true ;;
        expert) EXPERT=true ;;
        rollback) ROLLBACK=true ;;
    esac
done

# Mount necessary filesystems
mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sys /sys 2>/dev/null || true
mount -t devtmpfs dev /dev 2>/dev/null || true

# Create data partition mount point
mkdir -p /mnt/usb_data
# Try to mount USB data partition (third partition on USB)
for dev in /dev/sd??3 /dev/sd?3; do
    if [ -b "$dev" ]; then
        mount "$dev" /mnt/usb_data 2>/dev/null && break
    fi
done

# Set up Python environment
cd /opt/calcoc
if [ -f requirements.txt ] && command -v pip3 &>/dev/null; then
    pip3 install -r requirements.txt --quiet 2>/dev/null || true
fi

# Configure AI backend
EXTRA_ARGS=""
if [ "$NOAI" = true ]; then
    export AI_BACKEND=none
fi
if [ "$EXPERT" = true ]; then
    EXTRA_ARGS="--expert"
fi

# Handle rollback mode
if [ "$ROLLBACK" = true ]; then
    echo "=== ROLLBACK MODE ==="
    python3 -c "
from src.rollback.backup import BackupManager
from src.rollback.journal import Journal
journal = Journal('/mnt/usb_data/journal.db')
bm = BackupManager('/mnt/usb_data/backups', journal)
if bm.rollback_last():
    print('Rollback successful')
else:
    print('No operations to rollback')
"
    echo "Press Enter to continue to normal mode..."
    read
fi

# Start the web application
echo "========================================"
echo " AI PC Repair & Optimizer"
echo " Web interface: http://127.0.0.1:8080"
echo "========================================"

python3 -m src.core.app --host 0.0.0.0 --port 8080 $EXTRA_ARGS
STARTUP
chmod +x "${ROOTFS}/opt/calcoc/start.sh"

# Create init script
cat > "${ROOTFS}/etc/init.d/calcoc" << 'INITSCRIPT'
#!/bin/bash
### BEGIN INIT INFO
# Provides:          calcoc
# Required-Start:    $local_fs $network
# Default-Start:     2 3 4 5
# Short-Description: AI PC Repair & Optimizer
### END INIT INFO

case "$1" in
    start)
        /opt/calcoc/start.sh &
        ;;
    stop)
        pkill -f "src.core.app" || true
        ;;
esac
INITSCRIPT
chmod +x "${ROOTFS}/etc/init.d/calcoc"

# ---------------------------------------------------------------
# Step 3: Copy GRUB config
# ---------------------------------------------------------------
echo "[3/6] Setting up GRUB..."

cp "${PROJECT_DIR}/config/grub/grub.cfg" "${ISO_DIR}/boot/grub/grub.cfg"

# ---------------------------------------------------------------
# Step 4: Create squashfs
# ---------------------------------------------------------------
echo "[4/6] Creating squashfs filesystem..."

mkdir -p "${ISO_DIR}/live"
if command -v mksquashfs &>/dev/null; then
    mksquashfs "${ROOTFS}" "${ISO_DIR}/live/filesystem.squashfs" -comp xz -noappend
else
    echo "WARNING: mksquashfs not found. Creating placeholder."
    tar czf "${ISO_DIR}/live/filesystem.tar.gz" -C "${ROOTFS}" .
fi

# ---------------------------------------------------------------
# Step 5: Build ISO
# ---------------------------------------------------------------
echo "[5/6] Building ISO image..."

if command -v grub-mkrescue &>/dev/null; then
    grub-mkrescue -o "${OUTPUT}" "${ISO_DIR}" -- \
        -volid "AIREPAIR" 2>/dev/null
elif command -v xorriso &>/dev/null; then
    xorriso -as mkisofs \
        -o "${OUTPUT}" \
        -V "AIREPAIR" \
        -b boot/grub/i386-pc/eltorito.img \
        -no-emul-boot \
        -boot-load-size 4 \
        -boot-info-table \
        "${ISO_DIR}"
else
    echo "WARNING: Neither grub-mkrescue nor xorriso found."
    echo "Creating tar archive instead."
    tar czf "${OUTPUT%.iso}.tar.gz" -C "${ISO_DIR}" .
fi

# ---------------------------------------------------------------
# Step 6: Done
# ---------------------------------------------------------------
echo "[6/6] Build complete!"
echo "Output: ${OUTPUT}"
echo "Size: $(du -h "${OUTPUT}" 2>/dev/null | cut -f1 || echo 'N/A')"
